export const API_BASE = "";

export type SeriesMeta = {
  series_id: string;
  title_zh: string;
  source: string;
  role: string;
  unit: string;
  frequency: string;
  price_metrics: boolean;
  stale: boolean;
  notes?: string;
  observation_start?: string;
  observation_end?: string;
};

export type Observation = {
  observation_date: string;
  release_date: string;
  value: number | null;
};

export type QualityRow = {
  series_id: string;
  title_zh: string;
  source: string;
  frequency: string;
  unit: string;
  n_visible: number;
  n_vintage_rows: number;
  revised_observations: number;
  missing_rate_visible: number | null;
  long_gaps: number;
  release_before_observation: number;
  start: string | null;
  end: string | null;
  stale: boolean;
  pit_mode: string;
};

export type FailureRow = {
  source: string;
  series_id: string;
  url: string;
  http_status: number | null;
  error: string;
};

export type MatrixBlock = {
  eligible: boolean;
  reason: string | null;
  labels: string[];
  labels_zh?: string[];
  matrix: (number | null)[][];
  n_overlaps?: number;
  sample_start?: string;
  sample_end?: string;
  note?: string;
};

export type HeatRow = {
  series_id: string;
  label: string;
  stale: boolean;
  values: (number | null)[];
};

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`);
  if (!response.ok) {
    throw new Error(`${response.status} ${await response.text()}`);
  }
  return response.json() as Promise<T>;
}

export function fetchCatalog() {
  return getJson<{ series: SeriesMeta[] }>("/api/catalog");
}

export function fetchQuality(asOf: string) {
  return getJson<{ series: QualityRow[]; failures: FailureRow[] }>(`/api/quality?as_of=${asOf}`);
}

export function fetchSeries(seriesId: string, asOf: string) {
  return getJson<{ observations: Observation[]; title_zh: string; unit: string; caveat: string }>(
    `/api/series/${seriesId}?as_of=${asOf}`,
  );
}

export function fetchCorrelation(asOf: string, window: number) {
  return getJson<{
    price_returns: MatrixBlock;
    level_changes: MatrixBlock;
    rolling: { eligible: boolean; reason?: string; note?: string; points?: { observation_date: string; value: number }[] };
  }>(`/api/correlation?as_of=${asOf}&window=${window}`);
}

export function fetchHeatmap(asOf: string) {
  return getJson<{
    price_vol: { title: string; unit: string; caveat: string; columns: string[]; rows: HeatRow[] };
    level_scale: { title: string; unit: string; caveat: string; columns: string[]; rows: HeatRow[] };
  }>(`/api/heatmap?as_of=${asOf}`);
}

export function fetchMetrics(seriesId: string, asOf: string, window: number) {
  return getJson<{
    series_id: string;
    title_zh: string;
    eligible: boolean;
    reason: string | null;
    loss_var?: number;
    loss_expected_shortfall?: number;
    realized_vol?: number | null;
    max_drawdown?: number;
    sample_start?: string;
    sample_end?: string;
    n_returns?: number;
    return_definition?: string;
  }>(`/api/metrics/${seriesId}?as_of=${asOf}&window=${window}`);
}

export type PositionSeries = {
  market_id: string;
  title_zh: string;
  points: { observation_date: string; release_date: string; net_positions: number | null; open_interest: number | null }[];
};

export function fetchPositions(asOf: string) {
  return getJson<{ series: PositionSeries[]; caveat: string }>(`/api/positions?as_of=${asOf}`);
}

export type StructureEpisode = {
  start: string;
  end: string;
  change: number;
  direction: string;
  sp500_return: number | null;
  wti_return: number | null;
  vix_change: number | null;
  credit_change: number | null;
};

export type StructurePayload = {
  answer: string;
  caveat: string;
  latest_dgs10_change: number | null;
  episodes: { count: number; definition: string; items: StructureEpisode[] };
  tails: {
    sp500_wti_lower: { eligible: boolean; reason?: string | null; lambda?: number; n?: number; note: string };
    fast_rate_and_equity_loss: { eligible: boolean; reason?: string | null; probability?: number; n?: number; note: string };
  };
  network: {
    eligible: boolean;
    reason?: string | null;
    threshold?: number;
    n?: number;
    nodes: { id: string; name: string; degree: number }[];
    links: { source: string; target: string; value: number }[];
  };
  similar: {
    eligible: boolean;
    reason?: string | null;
    count: number;
    current_date?: string;
    nearest: { date: string; distance: number }[];
    caveat?: string;
  };
  markov: {
    eligible: boolean;
    reason?: string | null;
    method?: string;
    high_variance_spells?: number;
    latest_in_high_variance?: boolean;
    caveat?: string;
  };
  crises: {
    note: string;
    windows: {
      id: string;
      title: string;
      start: string;
      end: string;
      partial: boolean;
      dgs10_change: number | null;
      vix_change: number | null;
      sp500_return: number | null;
      wti_return: number | null;
    }[];
  };
};

export function fetchStructure(asOf: string, window: number) {
  return getJson<StructurePayload>(`/api/structure?as_of=${asOf}&window=${window}`);
}
