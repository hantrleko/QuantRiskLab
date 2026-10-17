import { useEffect, useMemo, useRef, useState } from "react";
import type { EChartsOption } from "echarts";
import { Chart, baseAxis, chartText, palette } from "./Chart";

const { muted } = chartText();
const PAIRS = [
  ["SP500", "DCOILWTICO"],
  ["DGS10", "DGS2"],
  ["T10Y2Y", "DGS10"],
  ["VIXCLS", "DGS10"],
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

type ReplayPayload = {
  as_of: string;
  actual_end: string | null;
  beyond_coverage: boolean;
  note: string;
  points: ReplayPoint[];
  events: { id: string; title: string; start: string; end: string; partial: boolean }[];
};

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(path);
  if (!response.ok) throw new Error(`${response.status} ${await response.text()}`);
  return response.json() as Promise<T>;
}

export function Studio({
  mode,
  asOf,
  windowSize,
}: {
  mode: "replay" | "explore" | "tails" | "compare" | "export";
  asOf: string;
  windowSize: number;
}) {
  if (mode === "replay") return <Replay asOf={asOf} windowSize={windowSize} />;
  if (mode === "explore") return <Explorer asOf={asOf} windowSize={windowSize} />;
  if (mode === "tails") return <Tails asOf={asOf} />;
  if (mode === "compare") return <Compare asOf={asOf} />;
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

function fmt(value: number | null, digits = 2) {
  return value == null || Number.isNaN(value) ? "—" : value.toFixed(digits);
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
  const chartHandle = useRef<import("echarts").ECharts | null>(null);
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
  const option = useMemo<EChartsOption>(() => {
    const axis = baseAxis();
    return {
      color: palette,
      tooltip: { trigger: "axis" },
      legend: { textStyle: { color: muted }, bottom: 0, type: "scroll" },
      grid: { left: 12, right: 16, top: 28, bottom: 72, containLabel: true },
      dataZoom: [{ type: "inside" }, { type: "slider", height: 16, bottom: 28 }],
      toolbox: { feature: { restore: { title: "重置缩放" } } },
      xAxis: { type: "time", ...axis },
      yAxis: { type: "value", name: "10年收益率变动（百分点）", ...axis },
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
            回放日 {current?.date ?? "无"}。10年收益率 {fmt(current?.dgs10 ?? null)}，63日变动 {fmt(current?.dgs10_change ?? null)}，VIX {fmt(current?.vix ?? null)}，
            股油相关 {fmt(current?.sp_wti_corr ?? null)}。样本到 {current?.date} 为止。
          </p>
          <Chart option={option} onReady={(chart) => { chartHandle.current = chart; }} />
        </>
      ) : null}
    </section>
  );
}

function Explorer({ asOf, windowSize }: { asOf: string; windowSize: number }) {
  const [pair, setPair] = useState<(typeof PAIRS)[number]>(PAIRS[0]);
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
        {PAIRS.map((item) => (
          <button key={item.join("-")} type="button" className={pair[0] === item[0] && pair[1] === item[1] ? "active" : ""} onClick={() => setPair(item)}>
            {item[0]} × {item[1]}
          </button>
        ))}
      </div>
      <Status status={query.status} error={query.error} />
      {query.status === "success" && body?.eligible ? (
        <>
          <p className="caption">
            {String(body.interpretation)} n={String(body.n)}，{String(body.sample_start)} 至 {String(body.sample_end)}。相关 {Number(body.correlation).toFixed(2)}。
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

function Tails({ asOf }: { asOf: string }) {
  const [alpha, setAlpha] = useState(0.05);
  const query = useQuery<Record<string, unknown>>(`/api/tails?as_of=${asOf}&alpha=${alpha}&left=SP500&right=DCOILWTICO`, `${asOf}:${alpha}`);
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

function Compare({ asOf }: { asOf: string }) {
  const query = useQuery<{ windows: Record<string, unknown>[]; note: string }>(
    `/api/compare?as_of=${asOf}&windows=taper,calm2017,covid,hike2022`,
    asOf,
  );
  const windows = query.data?.windows ?? [];
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
        { name: "标普 500", type: "bar", data: windows.map((item) => item.sp500_return as number | null) },
        { name: "WTI", type: "bar", data: windows.map((item) => item.wti_return as number | null) },
      ],
    };
  }, [windows]);
  return (
    <section className="panel">
      <h2>危机对照</h2>
      <p className="caption">{query.data?.note}</p>
      <Status status={query.status} error={query.error} />
      {query.status === "success" && windows.length === 0 ? <div className="empty">所选 as_of 之前没有这些事件窗口。</div> : null}
      {query.status === "success" && windows.length > 0 ? (
        <>
          <Chart option={option} height={280} />
          <ul>
            {windows.map((item) => (
              <li key={String(item.id)}>
                {String(item.title)} {String(item.start)} → {String(item.end)}。标普 {item.sp500_return == null ? String(item.sp500_return_status) : Number(item.sp500_return).toFixed(3)}
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
    const body = await response.json();
    setMessage(response.ok ? `已保存 ${body.experiment_id}` : `保存失败 ${response.status}`);
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
      <p className="caption">记录只写在本机 data/experiments，不作为公开原始数据发布。导出的摘要包含快照、方法和限制。</p>
      <div className="windows">
        <button type="button" onClick={() => void save()}>保存当前实验</button>
        <button
          type="button"
          onClick={() =>
            download(
              "quantrisklab-note.md",
              `# QuantRiskLab 研究摘要\n\n- as_of: ${asOf}\n- window: ${windowSize}\n- 方法: 已验收的简单收益、差分、有限样本 coexceedance 与 lift\n- 限制: 不是因果传染，不是交易建议。非正价格不计算复合收益。\n`,
              "text/markdown",
            )
          }
        >
          导出 Markdown
        </button>
        <button
          type="button"
          onClick={() => download("quantrisklab-note.csv", `as_of,window\n${asOf},${windowSize}\n`, "text/csv")}
        >
          导出 CSV
        </button>
      </div>
      {message ? <p className="caption">{message}</p> : null}
    </section>
  );
}
