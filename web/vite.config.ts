import { defineConfig } from "vite";

// base "./" so the built site works from any folder on a static host
export default defineConfig({
  base: "./",
  build: { target: "es2022", chunkSizeWarningLimit: 800 },
});
