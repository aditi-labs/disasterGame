import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// SPA: /operator and /projector are client routes served by the same index.html.
// The repository root ("../..", relative to this project) is allowed so the printed
// artwork (nepalmap.png) and the shared perception registration files are imported
// from their single source of truth.
export default defineConfig({
  plugins: [react()],
  server: { port: 5180, strictPort: true, fs: { allow: ["../.."] } },
});
