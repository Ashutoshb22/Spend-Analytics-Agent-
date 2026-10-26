import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The FastAPI backend owns these routes. In dev, Vite (on :5173) proxies them to
// the backend (:8000) so the React app can call them with same-origin relative URLs
// exactly like it does in production (where FastAPI serves the built app).
const API_ROUTES = ["/ask", "/metrics", "/breakdown", "/lines", "/upload", "/upload-doc", "/documents", "/savings", "/health", "/auth"];

export default defineConfig({
  plugins: [react()],
  // Both the dev server and the production build serve from the root path.
  server: {
    port: 5173,
    proxy: Object.fromEntries(
      API_ROUTES.map((route) => [route, { target: "http://127.0.0.1:8000", changeOrigin: true }])
    ),
  },
  build: { outDir: "dist" },
});
