import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "node:path";

// The dev server proxies /api to FastAPI so the browser sees one origin. That
// removes CORS from development entirely, and it means the production build -
// served as static files by the same FastAPI process - hits the same relative
// paths it did in development rather than a different absolute URL.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "./src") },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: process.env.VITE_API_TARGET ?? "http://127.0.0.1:8000",
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/api/, ""),
      },
    },
  },
  build: {
    outDir: "dist",
    // NOT the default "assets": the application has a client-side route at
    // /assets/:ticker, and nginx's rule for immutable bundle files was
    // matching it first and answering 404. Any refresh on an asset page died.
    // Renaming the build output removes the collision at its source rather
    // than papering over it with a regex that has to stay in sync with
    // whatever hash format Vite emits next.
    assetsDir: "static",
    // Charts and the query client are large and change rarely; splitting them
    // out keeps a routine deploy from invalidating them in every browser cache.
    rollupOptions: {
      output: {
        // Function form: Rollup dropped the object shorthand, and being
        // explicit about the match is clearer than a list of bare names anyway.
        manualChunks(id) {
          if (id.includes("lightweight-charts")) return "charts";
          if (/node_modules[\\/](react|react-dom|react-router|@tanstack)/.test(id)) {
            return "vendor";
          }
          return undefined;
        },
      },
    },
  },
});
