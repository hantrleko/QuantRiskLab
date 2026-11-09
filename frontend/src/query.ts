export const WINDOWS = [63, 126, 252] as const;
export const PAGES = ["overview", "pit", "research", "audit", "replay", "explore", "tails", "compare", "export"] as const;

export type WindowSize = (typeof WINDOWS)[number];
export type PageId = (typeof PAGES)[number];

export type QueryState = {
  asOf: string;
  windowSize: WindowSize;
  page: PageId;
};

function isIsoDate(value: string, today: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value) || value > today) return false;
  const [year, month, day] = value.split("-").map(Number);
  const parsed = new Date(Date.UTC(year, month - 1, day));
  return parsed.getUTCFullYear() === year && parsed.getUTCMonth() === month - 1 && parsed.getUTCDate() === day;
}

export function parseQuery(search: string, today: string): QueryState {
  const params = new URLSearchParams(search.startsWith("?") ? search.slice(1) : search);
  const requestedDate = params.get("as_of") ?? "";
  const requestedWindow = Number(params.get("window"));
  const requestedPage = params.get("page") ?? "";
  return {
    asOf: isIsoDate(requestedDate, today) ? requestedDate : today,
    windowSize: WINDOWS.includes(requestedWindow as WindowSize) ? (requestedWindow as WindowSize) : 63,
    page: PAGES.includes(requestedPage as PageId) ? (requestedPage as PageId) : "overview",
  };
}

export function writeQuery(asOf: string, windowSize: number, page: string): string {
  const params = new URLSearchParams();
  params.set("as_of", asOf);
  params.set("window", String(windowSize));
  params.set("page", page);
  return `?${params.toString()}`;
}
