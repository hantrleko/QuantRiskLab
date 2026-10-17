import { useEffect, useRef } from "react";
import * as echarts from "echarts";

export type ChartHandle = echarts.ECharts;

const text = "#d7e0ea";
const muted = "#8ea0b3";
const axis = "#314052";

export function baseAxis() {
  return {
    axisLine: { lineStyle: { color: axis } },
    axisLabel: { color: muted },
    splitLine: { lineStyle: { color: "#243140" } },
    nameTextStyle: { color: muted },
  };
}

export function Chart({
  option,
  height = 360,
  onReady,
}: {
  option: echarts.EChartsOption;
  height?: number;
  onReady?: (chart: echarts.ECharts) => void;
}) {
  const ref = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);

  useEffect(() => {
    if (!ref.current) {
      return;
    }
    const chart = echarts.init(ref.current, undefined, { renderer: "canvas" });
    chartRef.current = chart;
    const onResize = () => chart.resize();
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("resize", onResize);
      chart.dispose();
      chartRef.current = null;
    };
  }, []);

  const readyRef = useRef(onReady);
  readyRef.current = onReady;

  useEffect(() => {
    if (!chartRef.current) return;
    chartRef.current.setOption(option, true);
    readyRef.current?.(chartRef.current);
  }, [option]);

  return <div ref={ref} style={{ height, width: "100%" }} />;
}

export const palette = ["#8fb8c9", "#d4a574", "#9cbfa3", "#d08b8b", "#b7a6d6", "#c7c091"];

export function chartText() {
  return { text, muted };
}
