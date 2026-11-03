import { useEffect, useRef } from "react";
import { BarChart, GraphChart, HeatmapChart, LineChart, ScatterChart } from "echarts/charts";
import { GridComponent, LegendComponent, TooltipComponent, DataZoomComponent, ToolboxComponent, VisualMapComponent } from "echarts/components";
import * as echarts from "echarts/core";
import type { EChartsCoreOption } from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";

echarts.use([
  BarChart,
  GraphChart,
  HeatmapChart,
  LineChart,
  ScatterChart,
  GridComponent,
  LegendComponent,
  TooltipComponent,
  DataZoomComponent,
  ToolboxComponent,
  VisualMapComponent,
  CanvasRenderer,
]);

export type ChartHandle = {
  getDataURL: (opts?: { type?: "png" | "jpeg" | "svg"; pixelRatio?: number; backgroundColor?: string }) => string;
};

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
  option: EChartsCoreOption;
  height?: number;
  onReady?: (chart: ChartHandle) => void;
}) {
  const ref = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);
  const optionRef = useRef(option);
  const widthRef = useRef(0);
  optionRef.current = option;

  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    const chart = echarts.init(node, undefined, { renderer: "canvas" });
    chartRef.current = chart;
    const fit = () => {
      const host = ref.current;
      const current = chartRef.current;
      if (!host || !current) return;
      const width = host.clientWidth;
      const hostHeight = host.clientHeight;
      if (width < 2 || hostHeight < 2) return;
      const revealed = widthRef.current < 2;
      widthRef.current = width;
      if (revealed) current.setOption(optionRef.current, true);
      current.resize({ width, height: hostHeight });
    };
    const observer = new ResizeObserver(() => fit());
    observer.observe(node);
    window.addEventListener("resize", fit);
    fit();
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", fit);
      chart.dispose();
      chartRef.current = null;
      widthRef.current = 0;
    };
  }, []);

  const readyRef = useRef(onReady);
  readyRef.current = onReady;

  useEffect(() => {
    const chart = chartRef.current;
    const node = ref.current;
    if (!chart || !node) return;
    chart.setOption(option, true);
    if (node.clientWidth > 1 && node.clientHeight > 1) {
      widthRef.current = node.clientWidth;
      chart.resize({ width: node.clientWidth, height: node.clientHeight });
    }
    readyRef.current?.(chart);
  }, [option]);

  return <div ref={ref} className="chart-host" style={{ height, width: "100%" }} />;
}

export const palette = ["#8fb8c9", "#d4a574", "#9cbfa3", "#d08b8b", "#b7a6d6", "#c7c091"];

export function chartText() {
  return { text, muted };
}
