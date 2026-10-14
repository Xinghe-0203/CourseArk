import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";
export default defineConfig({
  plugins: [vue()],
  base: "/static/vue/",
  build: { outDir: "../webui_static/vue", emptyOutDir: true },
  server: { proxy: { "/api": "http://127.0.0.1:8848" } },
});
