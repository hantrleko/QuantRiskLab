import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const api = process.env.QRL_API ?? "http://127.0.0.1:8876";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5280,
    strictPort: true,
    proxy: { "/api": api, "/health": api },
  },
  preview: {
    host: "127.0.0.1",
    port: 5280,
    strictPort: true,
    proxy: { "/api": api, "/health": api },
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes("node_modules/react-dom") || id.includes("node_modules/react/")) return "react";
          if (id.includes("node_modules/echarts") || id.includes("node_modules/zrender")) return "echarts";
        },
      },
    },
  },
});
