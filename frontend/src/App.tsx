import { useEffect, useMemo, useState } from "react";
import type { EChartsOption } from "echarts";
import {
  fetchCatalog,
  fetchCorrelation,
  fetchHeatmap,
  fetchMetrics,
  fetchPositions,
  fetchQuality,
  fetchSeries,
  fetchStructure,
  type FailureRow,
  type HeatRow,
  type MatrixBlock,
  type Observation,
  type PositionSeries,
  type QualityRow,
  type SeriesMeta,
  type StructurePayload,
} from "./api";
import { Chart, baseAxis, chartText, palette } from "./Chart";

const TODAY = new Date().toISOString().slice(0, 10);
const { muted } = chartText();

function withinYears(points: Observation[], asOf: string, years: number | null): Observation[] {
  const capped = points.filter((point) => point.observation_date <= asOf && point.value !== null);
  if (!years) return capped;
  const start = new Date(asOf);
  start.setFullYear(start.getFullYear() - years);
  return capped.filter((point) => point.observation_date >= start.toISOString().slice(0, 10));
}

function lineOption(series: { name: string; points: Observation[] }[], yName: string): EChartsOption {
  const axis = baseAxis();
  return {
    color: palette,
    tooltip: { trigger: "axis" },
    legend: { textStyle: { color: muted }, top: 0 },
    grid: { left: 64, right: 18, top: 42, bottom: 64 },
    dataZoom: [{ type: "inside" }, { type: "slider", height: 18, bottom: 16 }],
    xAxis: { type: "time", ...axis },
    yAxis: { type: "value", name: yName, scale: true, ...axis },
    series: series.map((item) => ({
      name: item.name,
      type: "line",
      showSymbol: false,
      connectNulls: false,
      data: item.points.map((point) => [point.observation_date, point.value]),
    })),
  };
}

function heatOption(columns: string[], rows: HeatRow[], max: number, asPercent: boolean): EChartsOption {
  const axis = baseAxis();
  const data: [number, number, number][] = [];
  rows.forEach((row, rowIndex) => {
    row.values.forEach((value, colIndex) => {
      if (value !== null) data.push([colIndex, rowIndex, value]);
    });
  });
  return {
    tooltip: {
      formatter: (params) => {
        const item = params as { data?: [number, number, number] };
        if (!item.data) return "";
        const [col, row, value] = item.data;
        const shown = asPercent ? `${(value * 100).toFixed(1)}%` : value.toFixed(3);
        return `${rows[row]?.label ?? ""}<br/>${columns[col] ?? ""}：${shown}`;
      },
    },
    grid: { left: 150, right: 70, top: 16, bottom: 72 },
    xAxis: { type: "category", data: columns, ...axis, axisLabel: { color: muted, rotate: 45 } },
    yAxis: { type: "category", data: rows.map((row) => row.label), ...axis },
    visualMap: {
      min: 0,
      max,
      calculable: true,
      orient: "vertical",
      right: 0,
      top: "middle",
      textStyle: { color: muted },
      inRange: { color: ["#1d3a4a", "#8fb8c9", "#d4a574", "#d08b8b"] },
    },
    series: [{ type: "heatmap", data }],
  };
}

function matrixOption(block: MatrixBlock | null): EChartsOption {
  const axis = baseAxis();
  const labels = block?.labels_zh?.length ? block.labels_zh : block?.labels ?? [];
  const data: [number, number, number][] = [];
  (block?.matrix ?? []).forEach((row, rowIndex) => {
    row.forEach((value, colIndex) => {
      if (value !== null) data.push([colIndex, rowIndex, value]);
    });
  });
  return {
    tooltip: {
      formatter: (params) => {
        const item = params as { data?: [number, number, number] };
        if (!item.data) return "";
        const [col, row, value] = item.data;
        return `${labels[row] ?? ""} × ${labels[col] ?? ""}：${value.toFixed(2)}`;
      },
    },
    grid: { left: 150, right: 70, top: 16, bottom: 80 },
    xAxis: { type: "category", data: labels, ...axis, axisLabel: { color: muted, rotate: 30 } },
    yAxis: { type: "category", data: labels, ...axis },
    visualMap: {
      min: -1,
      max: 1,
      calculable: true,
      orient: "vertical",
      right: 0,
      top: "middle",
      textStyle: { color: muted },
      inRange: { color: ["#3d6f8a", "#1b242e", "#d4a574"] },
    },
    series: [{ type: "heatmap", data }],
  };
}

export function App() {
  const [asOf, setAsOf] = useState(TODAY);
  const [years, setYears] = useState<number | null>(10);
  const [windowSize, setWindowSize] = useState(63);
  const [catalog, setCatalog] = useState<SeriesMeta[]>([]);
  const [points, setPoints] = useState<Record<string, Observation[]>>({});
  const [latestMacro, setLatestMacro] = useState<Record<string, Observation[]>>({});
  const [quality, setQuality] = useState<QualityRow[]>([]);
  const [failures, setFailures] = useState<FailureRow[]>([]);
  const [heatmap, setHeatmap] = useState<Awaited<ReturnType<typeof fetchHeatmap>> | null>(null);
  const [correlation, setCorrelation] = useState<Awaited<ReturnType<typeof fetchCorrelation>> | null>(null);
  const [metrics, setMetrics] = useState<Awaited<ReturnType<typeof fetchMetrics>>[]>([]);
  const [positions, setPositions] = useState<PositionSeries[]>([]);
  const [positionNote, setPositionNote] = useState("");
  const [structure, setStructure] = useState<StructurePayload | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setError("");
      try {
        const catalogBody = await fetchCatalog();
        if (cancelled) return;
        const datasets = catalogBody.series;
        setCatalog(datasets);
        const priceIds = datasets.filter((item) => item.price_metrics).map((item) => item.series_id);
        const macroIds = datasets.filter((item) => item.role === "macro").map((item) => item.series_id);
        const levelIds = datasets
          .filter((item) => ["yield", "spread", "volatility_index", "macro"].includes(item.role))
          .map((item) => item.series_id);
        const [qualityBody, heatmapBody, correlationBody, positionBody, structureBody, seriesBodies, latestBodies, metricBodies] =
          await Promise.all([
            fetchQuality(asOf),
            fetchHeatmap(asOf),
            fetchCorrelation(asOf, windowSize),
            fetchPositions(asOf),
            fetchStructure(asOf, windowSize).catch(() => null),
            Promise.all(levelIds.map(async (id) => [id, (await fetchSeries(id, asOf)).observations] as const)),
            Promise.all(macroIds.map(async (id) => [id, (await fetchSeries(id, TODAY)).observations] as const)),
            Promise.all(priceIds.map((id) => fetchMetrics(id, asOf, windowSize))),
          ]);
        if (cancelled) return;
        setQuality(qualityBody.series);
        setFailures(qualityBody.failures);
        setHeatmap(heatmapBody);
        setCorrelation(correlationBody);
        setPositions(positionBody.series);
        setPositionNote(positionBody.caveat);
        setStructure(structureBody);
        setPoints(Object.fromEntries(seriesBodies));
        setLatestMacro(Object.fromEntries(latestBodies));
        setMetrics(metricBodies);
      } catch (exc) {
        if (!cancelled) setError(exc instanceof Error ? exc.message : "无法读取后端");
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [asOf, windowSize]);

  const levelSeries = catalog.filter((item) => item.role === "yield" || item.role === "spread");
  const vix = catalog.find((item) => item.role === "volatility_index");
  const macroSeries = catalog.filter((item) => item.role === "macro");
  const matrix = correlation?.price_returns.eligible ? correlation.price_returns : correlation?.level_changes ?? null;

  const macroOption = useMemo(
    () =>
      lineOption(
        levelSeries.map((item) => ({ name: item.title_zh, points: withinYears(points[item.series_id] ?? [], asOf, years) })),
        "百分点",
      ),
    [levelSeries, points, asOf, years],
  );
  const vixOption = useMemo(
    () => lineOption(vix ? [{ name: vix.title_zh, points: withinYears(points[vix.series_id] ?? [], asOf, years) }] : [], "指数点"),
    [vix, points, asOf, years],
  );
  const macroCharts = useMemo(
    () =>
      macroSeries.map((item) => {
        const yName = item.series_id === "CPIAUCSL" || /index/i.test(item.unit) ? "指数" : "百分点";
        return {
          id: item.series_id,
          title: item.title_zh,
          option: lineOption(
            [
              { name: `截至 ${asOf} 可见`, points: withinYears(points[item.series_id] ?? [], asOf, years) },
              { name: "截至今天可见的最新修订", points: withinYears(latestMacro[item.series_id] ?? [], TODAY, years) },
            ],
            yName,
          ),
        };
      }),
    [macroSeries, points, latestMacro, asOf, years],
  );
  const priceHeat = useMemo(
    () => heatOption(heatmap?.price_vol.columns ?? [], heatmap?.price_vol.rows ?? [], 1.2, true),
    [heatmap],
  );
  const levelHeat = useMemo(
    () => heatOption(heatmap?.level_scale.columns ?? [], heatmap?.level_scale.rows ?? [], 0.4, false),
    [heatmap],
  );
  const corrChart = useMemo(() => matrixOption(matrix), [matrix]);
  const varOption = useMemo<EChartsOption>(() => {
    const axis = baseAxis();
    const rows = metrics.filter((item) => item.eligible && item.loss_var !== undefined);
    return {
      color: palette,
      tooltip: { trigger: "axis" },
      legend: { textStyle: { color: muted } },
      grid: { left: 56, right: 16, top: 36, bottom: 48 },
      xAxis: { type: "category", data: rows.map((item) => item.title_zh), ...axis },
      yAxis: { type: "value", name: "损失幅度 %", ...axis },
      series: [
        { name: "5% 历史模拟 VaR", type: "bar", data: rows.map((item) => (item.loss_var ?? 0) * 100) },
        { name: "5% Expected Shortfall", type: "bar", data: rows.map((item) => (item.loss_expected_shortfall ?? 0) * 100) },
      ],
    };
  }, [metrics]);
  const cotOption = useMemo(
    () =>
      lineOption(
        positions.map((item) => ({
          name: item.title_zh,
          points: item.points
            .filter((point) => point.release_date <= asOf && point.net_positions !== null)
            .filter((point) => (years ? point.release_date >= shiftYears(asOf, years) : true))
            .map((point) => ({
              observation_date: point.release_date,
              release_date: point.release_date,
              value: point.net_positions,
            })),
        })),
        "净持仓（张）",
      ),
    [positions, asOf, years],
  );
  const rollingOption = useMemo(() => {
    const rolling = correlation?.rolling;
    if (!rolling?.eligible || !rolling.points) return lineOption([], "相关系数");
    return lineOption(
      [
        {
          name: rolling.note ?? "滚动相关",
          points: rolling.points.map((point) => ({
            observation_date: point.observation_date,
            release_date: point.observation_date,
            value: point.value,
          })),
        },
      ],
      "相关系数",
    );
  }, [correlation]);
  const episodeOption = useMemo<EChartsOption>(() => {
    const axis = baseAxis();
    const items = structure?.episodes.items ?? [];
    return {
      color: palette,
      tooltip: { trigger: "axis" },
      legend: { textStyle: { color: muted } },
      grid: { left: 64, right: 18, top: 36, bottom: 64 },
      xAxis: { type: "category", data: items.map((item) => item.end), ...axis, axisLabel: { color: muted, rotate: 40 } },
      yAxis: { type: "value", name: "10年收益率变动（百分点）", ...axis },
      series: [{ name: "窗口变动", type: "bar", data: items.map((item) => item.change) }],
    };
  }, [structure]);
  const networkOption = useMemo<EChartsOption>(() => {
    const nodes = structure?.network.nodes ?? [];
    const links = structure?.network.links ?? [];
    return {
      tooltip: {
        formatter: (params) => {
          const item = params as { dataType?: string; data?: { name?: string; source?: string; target?: string; value?: number } };
          if (item.dataType === "edge" && item.data) {
            return `${item.data.source} → ${item.data.target}：${item.data.value?.toFixed(2)}`;
          }
          return item.data?.name ?? "";
        },
      },
      series: [
        {
          type: "graph",
          layout: "force",
          roam: true,
          label: { show: true, color: muted },
          force: { repulsion: 180, edgeLength: 120 },
          lineStyle: { color: "#d4a574", curveness: 0.15 },
          data: nodes.map((node) => ({ name: node.name, value: node.degree, symbolSize: 18 + node.degree * 8 })),
          links: links.map((link) => {
            const source = nodes.find((node) => node.id === link.source)?.name ?? link.source;
            const target = nodes.find((node) => node.id === link.target)?.name ?? link.target;
            return { source, target, value: link.value, lineStyle: { width: 1 + Math.abs(link.value) * 3 } };
          }),
        },
      ],
    };
  }, [structure]);
  const similarOption = useMemo<EChartsOption>(() => {
    const axis = baseAxis();
    const nearest = structure?.similar.nearest ?? [];
    return {
      color: palette,
      tooltip: { trigger: "axis" },
      grid: { left: 48, right: 12, top: 16, bottom: 48 },
      xAxis: { type: "category", data: nearest.map((item) => item.date), ...axis, axisLabel: { color: muted, rotate: 40 } },
      yAxis: { type: "value", name: "距离", ...axis },
      series: [{ type: "bar", data: nearest.map((item) => item.distance) }],
    };
  }, [structure]);
  const crisisOption = useMemo<EChartsOption>(() => {
    const axis = baseAxis();
    const windows = structure?.crises.windows ?? [];
    return {
      color: palette,
      tooltip: { trigger: "axis" },
      legend: { textStyle: { color: muted } },
      grid: { left: 56, right: 16, top: 36, bottom: 48 },
      xAxis: { type: "category", data: windows.map((item) => item.title), ...axis },
      yAxis: { type: "value", name: "价格收益 %", ...axis },
      series: [
        { name: "标普 500", type: "bar", data: windows.map((item) => (item.sp500_return == null ? null : item.sp500_return * 100)) },
        { name: "WTI", type: "bar", data: windows.map((item) => (item.wti_return == null ? null : item.wti_return * 100)) },
      ],
    };
  }, [structure]);

  return (
    <div className="page">
      <header>
        <div>
          <div className="kicker">QuantRiskLab · V0.2</div>
          <h1>宏观与风险研究工作台</h1>
          <p className="sub">图上的点都来自本地库里的公开观测。没有序列时留空，不用假数据补。</p>
        </div>
        <div className="controls">
          <label>
            可见截止日期 as_of
            <input type="date" value={asOf} max={TODAY} onChange={(event) => setAsOf(event.target.value)} />
          </label>
          <label>
            历史窗口
            <div className="windows">
              {[2, 5, 10].map((value) => (
                <button key={value} className={years === value ? "active" : ""} type="button" onClick={() => setYears(value)}>
                  {value}年
                </button>
              ))}
              <button className={years === null ? "active" : ""} type="button" onClick={() => setYears(null)}>
                全部
              </button>
            </div>
          </label>
          <label>
            相关与波动窗口
            <div className="windows">
              {[63, 126, 252].map((value) => (
                <button
                  key={value}
                  className={windowSize === value ? "active" : ""}
                  type="button"
                  onClick={() => setWindowSize(value)}
                >
                  {value}日
                </button>
              ))}
            </div>
          </label>
        </div>
      </header>
      <div className="note">
        利率、利差和 VIX 按水平展示，不换算成债券收益。收益、实现波动率、回撤、历史模拟 VaR 和 Expected Shortfall 只用于价格或价格指数。
        本版不做策略回测，不提供买卖建议。
      </div>
      {error ? <div className="warn">后端没有返回数据：{error}</div> : null}

      <section className="panel">
        <h2>利率快速变化时的风险结构</h2>
        <p className="caption">{structure?.answer ?? "等待后端计算。"}</p>
        <p className="caption">{structure?.episodes.definition}</p>
        {structure ? <Chart option={episodeOption} height={320} /> : <div className="empty">还没有结构结果。</div>}
        <ul>
          {(structure?.episodes.items ?? []).map((item) => (
            <li key={`${item.start}-${item.end}`}>
              {item.start} → {item.end}，10 年收益率 {item.change >= 0 ? "+" : ""}
              {item.change.toFixed(2)} 个百分点（{item.direction}）
              {item.sp500_return == null ? "，标普 500 在该窗口没有可用价格" : `，标普 500 收益 ${(item.sp500_return * 100).toFixed(1)}%`}
              {item.wti_return == null ? "，WTI 没有可用价格" : `，WTI 收益 ${(item.wti_return * 100).toFixed(1)}%`}
              {item.vix_change == null ? "" : `，VIX ${item.vix_change >= 0 ? "+" : ""}${item.vix_change.toFixed(1)}`}
            </li>
          ))}
        </ul>
      </section>

      <div className="grid">
        <section className="panel">
          <h2>动态风险网络</h2>
          <p className="caption">
            {structure?.network.eligible
              ? `最近 ${structure.network.n} 个重叠观测。边表示绝对相关不低于 ${structure.network.threshold}。收益和利率差分可以相关，但利率差分不是债券收益。`
              : structure?.network.reason ?? "等待网络。"}
          </p>
          {structure?.network.eligible ? <Chart option={networkOption} height={380} /> : <div className="empty">{structure?.network.reason ?? "网络不可用。"}</div>}
        </section>
        <section className="panel">
          <h2>尾部共现与相似历史</h2>
          <p className="caption">{structure?.tails.sp500_wti_lower.note}</p>
          <p>
            {structure?.tails.sp500_wti_lower.eligible
              ? `标普 500 与 WTI 的下尾共现系数 λ = ${structure.tails.sp500_wti_lower.lambda?.toFixed(2)}（n=${structure.tails.sp500_wti_lower.n}）。`
              : structure?.tails.sp500_wti_lower.reason}
          </p>
          <p className="caption">{structure?.tails.fast_rate_and_equity_loss.note}</p>
          <p>
            {structure?.tails.fast_rate_and_equity_loss.eligible
              ? `利率单日变动处于最高 5% 时，股票收益落入自身最低 5% 的频率是 ${(
                  (structure.tails.fast_rate_and_equity_loss.probability ?? 0) * 100
                ).toFixed(1)}%。`
              : structure?.tails.fast_rate_and_equity_loss.reason}
          </p>
          <p className="caption">
            {structure?.similar.eligible
              ? `当前特征日 ${structure.similar.current_date}。距离不超过阈值的独立历史片段有 ${structure.similar.count} 次。${structure.similar.caveat ?? ""}`
              : structure?.similar.reason}
          </p>
          {structure?.similar.eligible ? <Chart option={similarOption} height={260} /> : null}
          <p className="caption">
            {structure?.markov.eligible
              ? `高方差段 ${structure.markov.high_variance_spells} 段，当前${structure.markov.latest_in_high_variance ? "处于" : "不处于"}高方差段。${structure.markov.caveat ?? ""}`
              : structure?.markov.reason}
          </p>
        </section>
      </div>

      <section className="panel">
        <h2>历史危机对照</h2>
        <p className="caption">{structure?.crises.note}</p>
        {structure?.crises.windows.length ? <Chart option={crisisOption} height={320} /> : <div className="empty">这个 as_of 之前没有预设对照窗口。</div>}
      </section>

      <section className="panel">
        <h2>利率与信用利差</h2>
        <p className="caption">折线图。纵轴是百分点，不是资产价格。</p>
        {levelSeries.length ? <Chart option={macroOption} /> : <div className="empty">没有下载到利率或利差序列。</div>}
      </section>

      <div className="grid">
        <section className="panel">
          <h2>VIX 水平</h2>
          <p className="caption">波动率指数。指数变动不是持仓收益。</p>
          {vix ? <Chart option={vixOption} height={300} /> : <div className="empty">没有 VIX 序列。</div>}
        </section>
        <section className="panel">
          <h2>宏观修订的 point-in-time</h2>
          <p className="caption">as_of 当时已发布的 vintage，以及今天可见的最新修订。修订不会提前出现。失业率和 CPI 都是水平，不是资产价格。</p>
          {macroCharts.length ? (
            macroCharts.map((item) => (
              <div key={item.id}>
                <p className="caption">{item.title}</p>
                <Chart option={item.option} height={300} />
              </div>
            ))
          ) : (
            <div className="empty">没有已入库的宏观 vintage。UNRATE 仍是数据缺口。</div>
          )}
        </section>
      </div>

      <section className="panel">
        <h2>季度实现波动率</h2>
        <p className="caption">{heatmap?.price_vol.caveat ?? "热力图只包含价格序列。"}</p>
        {heatmap?.price_vol.rows.length ? <Chart option={priceHeat} height={320} /> : <div className="empty">没有足够的价格序列。</div>}
      </section>

      <section className="panel">
        <h2>利率与利差的变动尺度</h2>
        <p className="caption">{heatmap?.level_scale.caveat ?? "这是水平差分的尺度，不是资产波动率。"}</p>
        {heatmap?.level_scale.rows.length ? <Chart option={levelHeat} height={340} /> : <div className="empty">没有日频水平序列。</div>}
      </section>

      <div className="grid">
        <section className="panel">
          <h2>{correlation?.price_returns.eligible ? "价格收益相关矩阵" : "水平差分相关矩阵"}</h2>
          <p className="caption">
            {matrix?.eligible
              ? `${matrix.note ?? ""} 样本 ${matrix.sample_start ?? ""} 至 ${matrix.sample_end ?? ""}，n=${matrix.n_overlaps ?? 0}。`
              : matrix?.reason ?? "等待序列。"}
          </p>
          {matrix?.eligible ? <Chart option={corrChart} height={380} /> : <div className="empty">{matrix?.reason ?? "相关矩阵不可用。"}</div>}
        </section>
        <section className="panel">
          <h2>历史模拟 VaR 与 Expected Shortfall</h2>
          <p className="caption">柱状图。纵轴是简单收益左尾的损失幅度，正数表示亏损。这不是策略业绩。</p>
          {metrics.some((item) => item.eligible) ? <Chart option={varOption} height={320} /> : <div className="empty">没有可计算 VaR 的价格序列。</div>}
          <ul>
            {metrics.map((item) => (
              <li key={item.series_id}>
                {item.title_zh}
                {item.eligible
                  ? `：${item.sample_start} 至 ${item.sample_end}，${item.n_returns} 个收益，${windowSize} 日实现波动率 ${
                      item.realized_vol == null ? "样本不足" : `${(item.realized_vol * 100).toFixed(1)}%`
                    }，最大回撤 ${((item.max_drawdown ?? 0) * 100).toFixed(1)}%。`
                  : `：${item.reason}`}
              </li>
            ))}
          </ul>
        </section>
      </div>

      <section className="panel">
        <h2>10年与2年收益率差分的滚动相关</h2>
        <p className="caption">{correlation?.rolling.note ?? correlation?.rolling.reason ?? "水平差分的滚动相关，不是收益相关。"}</p>
        {correlation?.rolling.eligible ? <Chart option={rollingOption} height={300} /> : <div className="empty">{correlation?.rolling.reason ?? "滚动相关不可用。"}</div>}
      </section>

      <section className="panel">
        <h2>CFTC 净持仓</h2>
        <p className="caption">{positionNote || "时间轴使用公布日。持仓张数不是价格。"}</p>
        {positions.length ? <Chart option={cotOption} /> : <div className="empty">没有匹配到的 CFTC 持仓。</div>}
      </section>

      <section className="panel">
        <h2>数据质量</h2>
        <p className="caption">缺失保持缺失。vintage 行数高于可见样本，说明修订被保留，而不是用最新值覆盖历史。</p>
        <div style={{ overflowX: "auto" }}>
          <table>
            <thead>
              <tr>
                <th>序列</th>
                <th>来源</th>
                <th>频率</th>
                <th>可见样本</th>
                <th>起止</th>
                <th>缺失率</th>
                <th>长缺口</th>
                <th>vintage 行</th>
                <th>有修订的观测</th>
                <th>发布早于观测</th>
                <th>状态</th>
              </tr>
            </thead>
            <tbody>
              {quality.map((row) => (
                <tr key={row.series_id}>
                  <td>
                    {row.title_zh}
                    <br />
                    {row.series_id}
                  </td>
                  <td>{row.source}</td>
                  <td>
                    {row.frequency}
                    <br />
                    {row.unit}
                  </td>
                  <td>{row.n_visible}</td>
                  <td>
                    {row.start} → {row.end}
                  </td>
                  <td>{row.missing_rate_visible == null ? "—" : `${(row.missing_rate_visible * 100).toFixed(1)}%`}</td>
                  <td>{row.long_gaps}</td>
                  <td>{row.n_vintage_rows}</td>
                  <td>{row.revised_observations}</td>
                  <td>{row.release_before_observation}</td>
                  <td>
                    {row.stale ? "滞后或停更" : "在更新窗口内"}
                    <br />
                    {row.pit_mode}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {failures.length ? (
        <section className="panel">
          <h2>下载障碍</h2>
          <table>
            <thead>
              <tr>
                <th>来源</th>
                <th>对象</th>
                <th>HTTP</th>
                <th>URL</th>
                <th>错误</th>
              </tr>
            </thead>
            <tbody>
              {failures.map((item) => (
                <tr key={`${item.source}-${item.series_id}-${item.url}`}>
                  <td>{item.source}</td>
                  <td>{item.series_id}</td>
                  <td>{item.http_status ?? "—"}</td>
                  <td className="rule">{item.url}</td>
                  <td className="rule">{item.error}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ) : null}

      <footer>
        <p>V0.1 不包含策略回测。页面上的数字不是可交易业绩。</p>
        <p>以后若做回测，必须同时报告 walk-forward、费用、参数敏感性、基准和样本外结果。</p>
        <p>
          as_of = {asOf}。相关窗口 = {windowSize} 个观测。
        </p>
      </footer>
    </div>
  );
}

function shiftYears(asOf: string, years: number): string {
  const start = new Date(asOf);
  start.setFullYear(start.getFullYear() - years);
  return start.toISOString().slice(0, 10);
}
