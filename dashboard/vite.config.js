import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// API_BASE in src/lib/api.js stays relative ("/api"). In dev, this proxy
// forwards it to the real API service so the browser never makes a
// cross-origin request and CORS never comes into play (brief §5.1).
// Production still needs the project owner's call between serving this
// build from the API's own origin or adding CORSMiddleware — this proxy
// only covers local development.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      "/api": {
        target: "http://localhost:8001",
        changeOrigin: true,
      },
    },
  },
});
