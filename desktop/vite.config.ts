import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Tauri 開發伺服器:固定埠、不要清螢幕(方便看編譯訊息)
export default defineConfig({
  plugins: [react()],
  clearScreen: false,
  server: {
    port: 1420,
    strictPort: true,
  },
});
