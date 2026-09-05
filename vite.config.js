import { resolve } from "node:path";

import { defineConfig } from "vite";

export default defineConfig({
  build: {
    rollupOptions: {
      input: {
        main: resolve(process.cwd(), "index.html"),
        replay: resolve(process.cwd(), "replay.html"),
        comparison: resolve(process.cwd(), "comparison.html"),
      },
    },
  },
});
