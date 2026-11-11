import { useEffect, useMemo, useRef, useState } from "react";
import type { EChartsOption } from "echarts";
import { fetchResearch, type ResearchPayload } from "./api";
import { Chart, baseAxis, chartText, palette, type ChartHandle } from "./Chart";

const { muted } = chartText();
const PAIRS = [
  ["SP500", "DCOILWTICO"],
  ["DGS10", "DGS2"],
  ["T10Y2Y", "DGS10"],
  ["VIXCLS", "DGS10"],
  ["DFII10", "T10YIE"],
] as const;

type ReplayPoint = {
  date: string;
  dgs10: number | null;
  dgs10_change: number | null;
  vix: number | null;
  sp500_return: number | null;
  wti_return: number | null;
  sp_wti_corr: number | null;
};

type CoverageRow = { rows: number; start: string | null; end: string | null; title_zh: string };

type VintagePoint = { observation_date: string; release_date: string; value: number | null };

function vintageOption(name: string, points: VintagePoint[], low: number, high: number): EChartsOption {
  const axis = baseAxis();
  return {
    color: palette,
    tooltip: { trigger: "axis" },
    grid: { left: 72, right: 12, top: 16, bottom: 28, containLabel: false },
    xAxis: { type: "time", ...axis },
    yAxis: { type: "value", name: "指数", nameLocation: "middle", nameGap: 48, min: low, max: high, scale: true, ...axis },
    series: [{ name, type: "line", showSymbol: false, connectNulls: false, data: points.map((point) => [point.observation_date, point.value]) }],
  };
}

function CpiCompare({ body }: { body: unknown }) {
  const cpi = body as {
    status?: string;
    title?: string;
    note?: string;
    reason?: string;
    revised_count?: number;
    later_release_count?: number;
    then?: VintagePoint[];
    now?: VintagePoint[];
  } | null;
  if (!cpi) return null;
  if (cpi.status !== "available") return <p className="caption">{cpi.reason}</p>;
  const values = [...(cpi.then ?? []), ...(cpi.now ?? [])]
    .map((point) => point.value)
    .filter((value): value is number => typeof value === "number" && Number.isFinite(value));
  if (!values.length) return <p className="caption">{cpi.reason ?? "没有可并排的 CPI 观测。"}</p>;
  const low = Math.min(...values);
  const high = Math.max(...values);
  const pad = (high - low) * 0.05 || 1;
  return (
    <>
      <p className="caption">
        {cpi.title}：同一观测月并排。数值不同的月份有 {cpi.revised_count ?? 0} 个。最新发布日晚于回放日的月份有 {cpi.later_release_count ?? 0} 个。{cpi.note}
      </p>
      <div className="grid">
        <div>
          <p className="caption">截面日可见</p>
          <Chart option={vintageOption("截面日可见", cpi.then ?? [], low - pad, high + pad)} height={260} />
        </div>
        <div>
          <p className="caption">库存最新版本</p>
          <Chart option={vintageOption("库存最新版本", cpi.now ?? [], low - pad, high + pad)} height={260} />
        </div>
      </div>
    </>
  );
}

type ReplayPayload = {
  as_of: string;
  actual_end: string | null;
  beyond_coverage: boolean;
  coverage?: Record<string, CoverageRow>;
  price_overlap_end?: string | null;
  note: string;
  points: ReplayPoint[];
  events: { id: string; title: string; start: string; end: string; partial: boolean }[];
};

function seriesVisibility(day: string, coverage: Record<string, CoverageRow> | undefined): string[] {
  if (!coverage) return [];
  const lines: string[] = [];
  for (const row of Object.values(coverage)) {
    const title = row.title_zh || "该序列";
    if (!row.start) {
      lines.push(`${title}在这个 as_of 下没有可见观测。`);
      continue;
    }
    if (day < row.start) lines.push(`${title}自 ${row.start.slice(0, 7)} 起可见`);
    else if (row.end && day > row.end) lines.push(`${title}可见至 ${row.end}`);
  }
  return lines;
}

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(path);
  if (!response.ok) throw new Error(`${response.status} ${await response.text()}`);
  return response.json() as Promise<T>;
}

export function Studio({
  mode,
  asOf,
  windowSize,
  equityId = "SP500",
  equityTitle = "股指",
}: {
  mode: "replay" | "explore" | "tails" | "compare" | "export";
  asOf: string;
  windowSize: number;
  equityId?: string;
  equityTitle?: string;
}) {
  if (mode === "replay") return <Replay asOf={asOf} windowSize={windowSize} />;
  if (mode === "explore") return <Explorer asOf={asOf} windowSize={windowSize} equityId={equityId} />;
  if (mode === "tails") return <Tails asOf={asOf} equityId={equityId} />;
  if (mode === "compare") return <Compare asOf={asOf} equityTitle={equityTitle} />;
  return <Experiments asOf={asOf} windowSize={windowSize} />;
}

function useQuery<T>(path: string, queryKey: string) {
  const serial = useRef(0);
  const [status, setStatus] = useState<"loading" | "success" | "empty" | "error">("loading");
  const [error, setError] = useState("");
  const [data, setData] = useState<T | null>(null);
  useEffect(() => {
    const id = ++serial.current;
    setStatus("loading");
    setError("");
    setData(null);
    getJson<T>(path)
      .then((body) => {
        if (serial.current !== id) return;
        const record = body as { points?: unknown[]; eligible?: boolean; windows?: unknown[] };
        const empty = Array.isArray(record.points) && record.points.length === 0;
        setData(body);
        setStatus(empty ? "empty" : "success");
      })
      .catch((exc: unknown) => {
        if (serial.current !== id) return;
        setStatus("error");
        setError(exc instanceof Error ? exc.message : "请求失败");
      });
  }, [path, queryKey]);
  return { status, error, data };
}

function fmt(value: unknown, digits = 2) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  return value.toFixed(digits);
}

function Status({ status, error }: { status: string; error: string }) {
  if (status === "loading") return <div className="note">正在按当前 as_of 计算，上一组结果已隐藏。</div>;
  if (status === "error") return <div className="warn">这次查询失败：{error}</div>;
  if (status === "empty") return <div className="empty">这个日期没有可展示的序列。没有用其他日期的结果填上。</div>;
  return null;
}

function Replay({ asOf, windowSize }: { asOf: string; windowSize: number }) {
  const query = useQuery<ReplayPayload>(`/api/replay?as_of=${asOf}&window=${windowSize}`, `${asOf}:${windowSize}`);
  const [cursor, setCursor] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const chartHandle = useRef<ChartHandle | null>(null);
  const points = useMemo(() => (query.data?.points ?? []).filter((point) => point.date <= asOf), [query.data, asOf]);
  useEffect(() => {
    setCursor(Math.max(points.length - 1, 0));
    setPlaying(false);
  }, [points]);
  useEffect(() => {
    if (!playing || points.length === 0) return;
    const timer = window.setInterval(() => {
      setCursor((value) => (value + 1 >= points.length ? 0 : value + 1));
    }, 700 / speed);
    return () => window.clearInterval(timer);
  }, [playing, points.length, speed]);
  const shown = points.slice(0, cursor + 1);
  const current = shown.at(-1);
  const coverageNotes = current ? seriesVisibility(current.date, query.data?.coverage) : [];
  const priceNotStarted = coverageNotes.some((line) => line.includes("起可见"));
  const [section, setSection] = useState<Record<string, unknown> | null>(null);
  useEffect(() => {
    if (!current || playing) return;
    const cursorDate = current.date;
    let cancelled = false;
    getJson<Record<string, unknown>>(`/api/section?as_of=${cursorDate}&window=${windowSize}`)
      .then((body) => {
        if (!cancelled) setSection(body);
      })
      .catch(() => {
        if (!cancelled) setSection(null);
      });
    return () => {
      cancelled = true;
    };
  }, [current?.date, playing, windowSize]);
  const option = useMemo<EChartsOption>(() => {
    const axis = baseAxis();
    return {
      color: palette,
      tooltip: { trigger: "axis" },
      legend: { textStyle: { color: muted }, bottom: 0, type: "scroll" },
      grid: { left: 72, right: 16, top: 16, bottom: 72, containLabel: false },
      dataZoom: [{ type: "inside" }, { type: "slider", height: 16, bottom: 28 }],
      toolbox: { feature: { restore: { title: "重置缩放" } } },
      xAxis: { type: "time", ...axis },
      yAxis: { type: "value", name: "10年收益率变动（百分点）", nameLocation: "middle", nameGap: 48, ...axis },
      series: [{ name: "10年收益率变动", type: "line", showSymbol: false, data: shown.map((point) => [point.date, point.dgs10_change]) }],
    };
  }, [shown]);
  return (
    <section className="panel">
      <h2>历史风险回放</h2>
      <p className="caption">{query.data?.note}</p>
      {query.data?.beyond_coverage ? <div className="warn">所选日期晚于快照中的最后观测 {query.data.actual_end}。图只画到实际可得终点。</div> : null}
      <Status status={query.status} error={query.error} />
      {query.status === "success" ? (
        <>
          <div className="windows">
            <button type="button" onClick={() => setPlaying((value) => !value)}>{playing ? "暂停" : "播放"}</button>
            {[1, 2, 4].map((value) => (
              <button key={value} type="button" className={speed === value ? "active" : ""} onClick={() => setSpeed(value)}>
                {value}x
              </button>
            ))}
            <button
              type="button"
              onClick={() => {
                const url = chartHandle.current?.getDataURL({ type: "png", pixelRatio: 2, backgroundColor: "#10140f" });
                if (!url) return;
                const link = document.createElement("a");
                link.href = url;
                link.download = `replay-${current?.date ?? asOf}.png`;
                link.click();
              }}
            >
              导出 PNG
            </button>
            <button
              type="button"
              onClick={() => {
                const rows = shown.filter((point) => point.dgs10_change != null);
                const values = rows.map((point) => point.dgs10_change as number);
                const min = Math.min(...values);
                const max = Math.max(...values);
                const width = 960;
                const height = 320;
                const poly = rows
                  .map((point, index) => {
                    const x = (index / Math.max(rows.length - 1, 1)) * (width - 40) + 20;
                    const y = height - 20 - ((point.dgs10_change as number) - min) / (max - min || 1) * (height - 40);
                    return `${x.toFixed(1)},${y.toFixed(1)}`;
                  })
                  .join(" ");
                const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}"><rect width="100%" height="100%" fill="#10140f"/><text x="20" y="18" fill="#d7e0ea">10年收益率变动，回放至 ${current?.date ?? asOf}</text><polyline fill="none" stroke="#8fb8c9" stroke-width="2" points="${poly}"/></svg>`;
                const url = URL.createObjectURL(new Blob([svg], { type: "image/svg+xml" }));
                const link = document.createElement("a");
                link.href = url;
                link.download = `replay-${current?.date ?? asOf}.svg`;
                link.click();
                URL.revokeObjectURL(url);
              }}
            >
              导出 SVG
            </button>
            {(query.data?.events ?? []).map((event) => (
              <button
                key={event.id}
                type="button"
                onClick={() => {
                  const index = points.findIndex((point) => point.date >= event.end);
                  setCursor(index === -1 ? points.length - 1 : index);
                  setPlaying(false);
                }}
              >
                {event.title}
              </button>
            ))}
          </div>
          <input
            type="range"
            min={0}
            max={Math.max(points.length - 1, 0)}
            value={Math.min(cursor, Math.max(points.length - 1, 0))}
            onChange={(event) => {
              setPlaying(false);
              setCursor(Number(event.target.value));
            }}
          />
          <p className="caption">
            回放日 {current?.date ?? "无"}。10年收益率 {fmt(current?.dgs10 ?? null)}，{windowSize}日变动 {fmt(current?.dgs10_change ?? null)}，VIX {fmt(current?.vix ?? null)}，
            股油相关 {fmt(current?.sp_wti_corr ?? null)}。
            {coverageNotes.length ? `${coverageNotes.join("。")}。` : ""}
            {current && current.sp_wti_corr == null && !priceNotStarted ? "窗口内有效重叠收益少于 30 个，股油相关留空。" : ""}
            {current && current.sp_wti_corr != null && query.data?.price_overlap_end && current.date > query.data.price_overlap_end
              ? `股油相关用到 ${query.data.price_overlap_end} 为止的重叠收益。`
              : ""}
          </p>
          <p className="caption">
            {playing
              ? "播放时不重复请求截面。"
              : section && section.as_of === current?.date
                ? `该日截面：网络${(section.network as { eligible?: boolean; links?: unknown[] } | undefined)?.eligible ? ` ${(section.network as { links?: unknown[] }).links?.length ?? 0} 条边` : "样本不足"}。${(() => {
                    const crowding = section.crowding as { markets?: unknown[]; reason?: string } | undefined;
                    const count = crowding?.markets?.length ?? 0;
                    return count === 0 ? crowding?.reason ?? "这个 as_of 看不到 CFTC 持仓。" : `持仓 ${count} 个市场。`;
                  })()}${String(section.note ?? "")}`
                : "正在读取该日截面。"}
          </p>
          {!playing && section && section.as_of === current?.date
            ? ((section.revisions as { series_id: string; status: string; note?: string; reason?: string; later_known_at_as_of?: boolean }[] | undefined) ?? []).map((item) => (
            <p key={item.series_id} className="caption">
              {item.series_id}：{item.status === "unavailable" ? item.reason : item.note}
              {item.later_known_at_as_of === false ? " 终值是事后信息。" : ""}
            </p>
          ))
            : null}
          {!playing && section && section.as_of === current?.date ? <CpiCompare body={section.cpi} /> : null}
          <Chart option={option} onReady={(chart) => { chartHandle.current = chart; }} />
        </>
      ) : null}
    </section>
  );
}

function Explorer({ asOf, windowSize, equityId }: { asOf: string; windowSize: number; equityId: string }) {
  const pairs = useMemo<[string, string][]>(
    () => [
      [equityId, "DCOILWTICO"],
      ...PAIRS.filter((item) => item[0] !== "SP500" && item[0] !== equityId).map(
        (item) => [item[0], item[1]] as [string, string],
      ),
    ],
    [equityId],
  );
  const [pair, setPair] = useState<[string, string]>([equityId, "DCOILWTICO"]);
  useEffect(() => {
    setPair([equityId, "DCOILWTICO"]);
  }, [equityId]);
  const query = useQuery<Record<string, unknown>>(
    `/api/explore?as_of=${asOf}&window=${windowSize}&left=${pair[0]}&right=${pair[1]}`,
    `${asOf}:${windowSize}:${pair.join(":")}`,
  );
  const body = query.data;
  const scatter = (body?.scatter as { date: string; left: number; right: number }[] | undefined) ?? [];
  const rolling = (body?.rolling as { date: string; value: number }[] | undefined) ?? [];
  const option = useMemo<EChartsOption>(() => {
    const axis = baseAxis();
    return {
      color: palette,
      tooltip: { trigger: "item" },
      grid: { left: 12, right: 16, top: 24, bottom: 48, containLabel: true },
      xAxis: { type: "value", name: String(body?.left_transform ?? ""), ...axis },
      yAxis: { type: "value", name: String(body?.right_transform ?? ""), ...axis },
      series: [{ type: "scatter", data: scatter.map((point) => [point.left, point.right, point.date]) }],
    };
  }, [scatter, body]);
  const rollOption = useMemo<EChartsOption>(() => {
    const axis = baseAxis();
    return {
      color: palette,
      tooltip: { trigger: "axis" },
      grid: { left: 12, right: 16, top: 24, bottom: 48, containLabel: true },
      xAxis: { type: "time", ...axis },
      yAxis: { type: "value", name: "滚动相关", ...axis },
      series: [{ type: "line", showSymbol: false, data: rolling.map((point) => [point.date, point.value]) }],
    };
  }, [rolling]);
  return (
    <section className="panel">
      <h2>交互风险探索</h2>
      <div className="windows">
        {pairs.map((item) => (
          <button key={item.join("-")} type="button" className={pair[0] === item[0] && pair[1] === item[1] ? "active" : ""} onClick={() => setPair(item)}>
            {item[0]} × {item[1]}
          </button>
        ))}
      </div>
      <Status status={query.status} error={query.error} />
      {query.status === "success" && body?.eligible ? (
        <>
          <p className="caption">
            {String(body.interpretation)} 窗口样本 n={String(body.n)}，{String(body.sample_start)} 至 {String(body.sample_end)}。相关 {Number(body.correlation).toFixed(2)}。
            滚动相关在完整可见历史上按 63 日计算，再截取最近一段显示。
            {body.mechanical ? " 这是机械关系。" : ""}
          </p>
          <Chart option={option} height={280} />
          <Chart option={rollOption} height={240} />
        </>
      ) : null}
      {query.status === "success" && body && body.eligible === false ? <div className="empty">{String(body.reason)}</div> : null}
    </section>
  );
}

function Tails({ asOf, equityId }: { asOf: string; equityId: string }) {
  const [alpha, setAlpha] = useState(0.05);
  const query = useQuery<Record<string, unknown>>(
    `/api/tails?as_of=${asOf}&alpha=${alpha}&left=${equityId}&right=DCOILWTICO`,
    `${asOf}:${alpha}:${equityId}`,
  );
  const body = query.data;
  const sensitivity = (body?.sensitivity as { alpha: number; lift?: number | null; n_joint_tail?: number; eligible: boolean }[] | undefined) ?? [];
  const option = useMemo<EChartsOption>(() => {
    const axis = baseAxis();
    return {
      color: palette,
      tooltip: { trigger: "axis" },
      grid: { left: 12, right: 16, top: 24, bottom: 48, containLabel: true },
      xAxis: { type: "category", data: sensitivity.map((item) => String(item.alpha)), ...axis },
      yAxis: { type: "value", name: "lift", ...axis },
      series: [{ type: "bar", data: sensitivity.map((item) => item.lift ?? null) }],
    };
  }, [sensitivity]);
  return (
    <section className="panel">
      <h2>尾部风险实验室</h2>
      <p className="caption">有限样本阈值共现和 lift。不是渐近尾部依赖系数，也不是因果传染。</p>
      <div className="windows">
        {[0.01, 0.05, 0.1].map((value) => (
          <button key={value} type="button" className={alpha === value ? "active" : ""} onClick={() => setAlpha(value)}>
            α={value}
          </button>
        ))}
      </div>
      <Status status={query.status} error={query.error} />
      {query.status === "success" && body?.eligible ? (
        <>
          <p className="caption">
            n={String(body.n)}，联合尾部 {String(body.n_joint_tail)} 个。coexceedance={Number(body.coexceedance).toFixed(2)}，独立基准约 {String(body.independence_coexceedance)}。
            lift={Number(body.lift).toFixed(2)}，独立基准为 1。
          </p>
          <Chart option={option} height={240} />
          <p className="caption">尾部日期：{((body.events as string[] | undefined) ?? []).slice(0, 12).join("，") || "无"}</p>
        </>
      ) : null}
      {query.status === "success" && body && body.eligible === false ? <div className="empty">{String(body.reason)}</div> : null}
    </section>
  );
}

function Compare({ asOf, equityTitle }: { asOf: string; equityTitle: string }) {
  const [customStart, setCustomStart] = useState("");
  const [customEnd, setCustomEnd] = useState("");
  const custom = customStart && customEnd ? `&start=${customStart}&end=${customEnd}` : "";
  const query = useQuery<{ windows: Record<string, unknown>[]; note: string; equity_title?: string }>(
    `/api/compare?as_of=${asOf}&windows=gfc,taper,calm2017,covid,hike2022${custom}`,
    `${asOf}:${customStart}:${customEnd}`,
  );
  const windows = query.data?.windows ?? [];
  const label = query.data?.equity_title || equityTitle;
  const option = useMemo<EChartsOption>(() => {
    const axis = baseAxis();
    return {
      color: palette,
      tooltip: { trigger: "axis" },
      legend: { bottom: 0, textStyle: { color: muted } },
      grid: { left: 12, right: 16, top: 24, bottom: 64, containLabel: true },
      xAxis: { type: "category", data: windows.map((item) => String(item.title)), ...axis },
      yAxis: { type: "value", name: "价格收益", ...axis },
      series: [
        { name: label, type: "bar", data: windows.map((item) => (item.equity_return ?? item.sp500_return) as number | null) },
        { name: "WTI", type: "bar", data: windows.map((item) => item.wti_return as number | null) },
      ],
    };
  }, [windows, label]);
  return (
    <section className="panel">
      <h2>危机对照</h2>
      <p className="caption">{query.data?.note}</p>
      <div className="windows">
        <label>
          自选开始
          <input type="date" value={customStart} max={asOf} onChange={(event) => setCustomStart(event.target.value)} />
        </label>
        <label>
          自选结束
          <input type="date" value={customEnd} max={asOf} onChange={(event) => setCustomEnd(event.target.value)} />
        </label>
      </div>
      <Status status={query.status} error={query.error} />
      {query.status === "success" && windows.length === 0 ? <div className="empty">所选 as_of 之前没有这些事件窗口。</div> : null}
      {query.status === "success" && windows.length > 0 ? (
        <>
          <Chart option={option} height={280} />
          <ul>
            {windows.map((item) => (
              <li key={String(item.id)}>
                {String(item.title)} {String(item.start)} → {String(item.end)}。{label}{" "}
                {(item.equity_return ?? item.sp500_return) == null
                  ? String(item.equity_return_status ?? item.sp500_return_status)
                  : Number(item.equity_return ?? item.sp500_return).toFixed(3)}
                ，WTI {item.wti_return == null ? String(item.wti_return_status) : Number(item.wti_return).toFixed(3)}
                ，10年变动 {item.dgs10_change == null ? String(item.dgs10_change_status) : Number(item.dgs10_change).toFixed(2)}
              </li>
            ))}
          </ul>
        </>
      ) : null}
    </section>
  );
}

function Experiments({ asOf, windowSize }: { asOf: string; windowSize: number }) {
  const [message, setMessage] = useState("");
  async function save() {
    const response = await fetch("/api/experiments", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ as_of: asOf, window: windowSize, method: "replay+explore+tails", note: "本地研究记录，不进入公开数据包。" }),
    });
    const body = (await response.json().catch(() => ({}))) as { experiment_id?: string; detail?: string };
    setMessage(response.ok ? `已保存 ${body.experiment_id}` : `保存失败 ${response.status}${body.detail ? `：${body.detail}` : ""}`);
  }
  function download(filename: string, content: string, type: string) {
    const url = URL.createObjectURL(new Blob([content], { type }));
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    link.click();
    URL.revokeObjectURL(url);
  }
  return (
    <section className="panel">
      <h2>研究实验与导出</h2>
      <p className="caption">
        记录只写在本机 data/experiments，不作为公开原始数据发布。公网页面不把实验写到服务器。导出仍可用。CSV、Markdown 和 LaTeX 使用这次 as_of 与窗口的同一张描述性表。样本不足的期限不填系数。
      </p>
      <div className="windows">
        <button type="button" onClick={() => void save()}>保存当前实验</button>
        {(
          [
            ["md", "导出 Markdown"],
            ["csv", "导出 CSV"],
            ["tex", "导出 LaTeX"],
          ] as const
        ).map(([format, label]) => (
          <button
            key={format}
            type="button"
            onClick={() => {
              void fetch(`/api/note?as_of=${asOf}&window=${windowSize}&format=${format}`)
                .then(async (response) => {
                  if (!response.ok) throw new Error(`${response.status} ${await response.text()}`);
                  const extension = format === "tex" ? "tex" : format;
                  download(`quantrisklab-note-${asOf}-w${windowSize}.${extension}`, await response.text(), "text/plain");
                  setMessage("已导出当前查询的描述性结果。");
                })
                .catch((exc: unknown) => setMessage(exc instanceof Error ? exc.message : "导出失败"));
            }}
          >
            {label}
          </button>
        ))}
      </div>
      {message ? <p className="caption">{message}</p> : null}
    </section>
  );
}

export function ResearchMethods({
  body,
  asOf,
  windowSize,
}: {
  body: ResearchPayload | null;
  asOf: string;
  windowSize: number;
}) {
  const [override, setOverride] = useState<ResearchPayload | null>(null);
  const [equityWeight, setEquityWeight] = useState(0.5);
  const [weightError, setWeightError] = useState("");
  useEffect(() => {
    setOverride(null);
  }, [body]);
  const view = override ?? body;
  const equityTitle = view?.equity_title || "股指";
  const decomposition = view?.decomposition;
  const points = decomposition?.points ?? [];
  const splitOption = useMemo<EChartsOption>(() => {
    const axis = baseAxis();
    return {
      color: palette,
      tooltip: { trigger: "axis" },
      legend: { bottom: 0, textStyle: { color: muted } },
      grid: { left: 12, right: 16, top: 24, bottom: 64, containLabel: true },
      xAxis: { type: "time", ...axis },
      yAxis: { type: "value", name: "百分点", nameGap: 18, ...axis },
      series: [
        { name: "名义", type: "line", showSymbol: false, data: points.map((point) => [point.date, point.nominal]) },
        { name: "实际", type: "line", showSymbol: false, data: points.map((point) => [point.date, point.real]) },
        { name: "盈亏平衡", type: "line", showSymbol: false, data: points.map((point) => [point.date, point.breakeven]) },
        { name: "残差", type: "line", showSymbol: false, data: points.map((point) => [point.date, point.residual]) },
      ],
    };
  }, [points]);
  const horizons = view?.local_projection.horizons ?? [];
  const projectionOption = useMemo<EChartsOption>(() => {
    const axis = baseAxis();
    const ready = horizons.filter((item) => item.eligible && item.beta != null);
    return {
      color: palette,
      tooltip: { trigger: "axis" },
      legend: { bottom: 0, textStyle: { color: muted } },
      grid: { left: 12, right: 16, top: 24, bottom: 64, containLabel: true },
      xAxis: { type: "category", data: ready.map((item) => `${item.horizon}`), ...axis },
      yAxis: { type: "value", name: "系数", nameGap: 18, ...axis },
      series: [
        { name: "系数", type: "line", data: ready.map((item) => item.beta ?? null) },
        { name: "95% 下沿", type: "line", data: ready.map((item) => item.ci95?.[0] ?? null) },
        { name: "95% 上沿", type: "line", data: ready.map((item) => item.ci95?.[1] ?? null) },
      ],
    };
  }, [horizons]);
  const shares = view?.euler.shares ?? [];
  const shrunkShares = view?.euler.shrinkage?.shares ?? [];
  const shareOption = useMemo<EChartsOption>(() => {
    const axis = baseAxis();
    return {
      color: palette,
      tooltip: { trigger: "axis" },
      legend: { bottom: 0, textStyle: { color: muted } },
      grid: { left: 12, right: 16, top: 24, bottom: 64, containLabel: true },
      xAxis: { type: "category", data: view?.euler.names ?? [], ...axis },
      yAxis: { type: "value", name: "方差份额", nameGap: 18, ...axis },
      series: [
        { name: "样本协方差", type: "bar", data: shares },
        { name: "收缩协方差", type: "bar", data: shrunkShares },
      ],
    };
  }, [view?.euler.names, shares, shrunkShares]);
  return (
    <section className="panel">
      <h2>利率分解、风险贡献与约化式投影</h2>
      <p className="caption">{view?.note}</p>
      {!view ? <div className="empty">这次查询没有带回研究模块。</div> : null}
      {decomposition?.status === "unavailable" ? <div className="empty">{decomposition.reason}</div> : null}
      {decomposition?.status === "available" && decomposition.latest ? (
        <>
          <p className="caption">
            {decomposition.latest.date}：名义 {fmt(decomposition.latest.nominal)}，实际 {fmt(decomposition.latest.real)}，盈亏平衡 {fmt(decomposition.latest.breakeven)}，残差 {fmt(decomposition.latest.residual)}。
            {decomposition.note}
          </p>
          <Chart option={splitOption} height={280} />
        </>
      ) : null}
      {decomposition?.dollar?.status === "available" ? (
        <p className="caption">
          广义美元指数 {decomposition.dollar.date} 为 {fmt(decomposition.dollar.level)}，63 个观测的水平差 {fmt(decomposition.dollar.change_63)}。{decomposition.dollar.note}
        </p>
      ) : (
        <p className="caption">{decomposition?.dollar?.reason}</p>
      )}
      <h3>方差贡献</h3>
      <div className="windows">
        <label>
          {equityTitle}权重
          <input
            type="number"
            min={0}
            max={1}
            step={0.05}
            value={equityWeight}
            onChange={(event) => setEquityWeight(Number(event.target.value))}
          />
        </label>
        <button
          type="button"
          onClick={() => {
            const equity = Math.round(equityWeight * 1000) / 1000;
            const oil = Math.round((1 - equity) * 1000) / 1000;
            if (equity < 0 || oil < 0 || Math.abs(equity + oil - 1) > 1e-6) {
              setWeightError("权重不能为负，并且需要加总为 1");
              return;
            }
            setWeightError("");
            void fetchResearch(asOf, windowSize, `${equity},${oil}`)
              .then(setOverride)
              .catch((exc: unknown) => setWeightError(exc instanceof Error ? exc.message : "权重查询失败"));
          }}
        >
          按该权重重算
        </button>
      </div>
      {weightError ? <div className="warn">{weightError}</div> : null}
      {view?.euler.eligible ? (
        <>
          <p className="caption">
            权重 {view.euler.weights?.map((item) => item.toFixed(2)).join(" / ")}。{view.euler.sample_start} 至 {view.euler.sample_end}，n={view.euler.n}。
            收缩强度 {fmt(view.euler.shrinkage?.intensity, 3)}。{view.euler.note}
          </p>
          <Chart option={shareOption} height={220} />
        </>
      ) : (
        <div className="empty">{view?.euler.reason ?? "没有方差贡献。"}</div>
      )}
      <h3>局部投影</h3>
      <p className="caption">
        {view?.local_projection.label}
        {view?.local_projection.controls?.length ? ` 控制变量：${view.local_projection.controls.join("、")}。` : ""}
      </p>
      {view?.local_projection.eligible ? <Chart option={projectionOption} height={260} /> : <div className="empty">{view?.local_projection.reason}</div>}
      <ul>
        {horizons.map((item) => (
          <li key={item.horizon}>
            {item.horizon} 日：
            {item.eligible
              ? `系数 ${fmt(item.beta, 3)}，标准误 ${fmt(item.se, 3)}，95% 区间 ${fmt(item.ci95?.[0], 3)} 至 ${fmt(item.ci95?.[1], 3)}，n=${item.n}`
              : item.reason}
          </li>
        ))}
      </ul>
      <h3>条件分位数差值</h3>
      <p className="caption">{view?.covar?.note} {view?.covar?.equity_on_oil.label}</p>
      <p className="caption">
        {equityTitle}对原油：{view?.covar?.equity_on_oil.eligible ? fmt(view.covar.equity_on_oil.delta_covar, 4) : view?.covar?.equity_on_oil.reason ?? "没有结果"}。
        {equityTitle}对 10 年收益率变动：{view?.covar?.equity_on_yield_change.eligible ? fmt(view.covar.equity_on_yield_change.delta_covar, 4) : view?.covar?.equity_on_yield_change.reason ?? "没有结果"}。
      </p>
      <h3>信用利差与期货持仓</h3>
      {view?.funding.status === "available" && view.funding.latest ? (
        <p className="caption">
          OAS {view.funding.latest.date} 为 {fmt(view.funding.latest.oas)}，21 个观测变动 {fmt(view.funding.latest.change_21)}，z={fmt(view.funding.latest.zscore)}。{view.funding.note}
        </p>
      ) : (
        <p className="caption">{view?.funding.reason}</p>
      )}
      {view?.crowding.status === "unavailable" ? <div className="empty">{view.crowding.reason}</div> : null}
      {view && view.crowding.markets.length > 0 ? (
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>市场</th>
                <th>观测日</th>
                <th>发布日</th>
                <th>净持仓/未平仓</th>
                <th>z</th>
              </tr>
            </thead>
            <tbody>
              {view.crowding.markets.map((market) => (
                <tr key={market.market_id}>
                  <td>{market.title_zh}</td>
                  <td>{market.observation_date}</td>
                  <td>{market.release_date}</td>
                  <td>{fmt(market.net_over_oi, 3)}</td>
                  <td>{fmt(market.zscore)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      <p className="caption">{view?.crowding.note}</p>
      <h3>修订差</h3>
      <ul>
        {(view?.revisions ?? []).map((item) => (
          <li key={item.series_id}>
            {item.series_id}：{item.status === "unavailable" ? item.reason : item.note}
            {item.revised_count != null ? ` 有差异的观测 ${item.revised_count} 个。` : ""}
            {item.later_known_at_as_of === false ? " 终版发布日晚于 as_of，回放当日看不到。" : ""}
          </li>
        ))}
      </ul>
    </section>
  );
}
