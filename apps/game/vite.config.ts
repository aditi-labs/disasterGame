import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// SPA: /operator and /projector are client routes served by the same index.html.
export default defineConfig({
  plugins: [react()],
  server: { port: 5180, strictPort: true },
});
