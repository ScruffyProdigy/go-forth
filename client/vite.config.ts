/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

// 5175: offset from rpslr's 5174 and the Lobby's 5173 so all three can run at
// once. strictPort means a collision fails loudly instead of silently moving
// the client off the port the Lobby's launch URL points at.
const CLIENT_PORT = 5175;

export default defineConfig({
  plugins: [react()],
  server: {
    port: CLIENT_PORT,
    strictPort: true,
  },
  preview: {
    port: CLIENT_PORT,
    strictPort: true,
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: './src/test/setup.ts',
    css: false,
  },
});
