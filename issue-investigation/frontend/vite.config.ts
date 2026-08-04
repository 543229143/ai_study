import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

export default defineConfig({
  plugins: [vue()],
  server: {
    host: true,
    port: 5173,
    proxy: {
      "/runs": { target: "http://127.0.0.1:8000", changeOrigin: true, ws: true },
      "/tools": { target: "http://127.0.0.1:8000", changeOrigin: true },
      "/events": { target: "http://127.0.0.1:8000", changeOrigin: true },
      "/health": { target: "http://127.0.0.1:8000", changeOrigin: true },
    },
  },
});
