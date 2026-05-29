import { fileURLToPath } from 'node:url';
import { defineConfig } from 'vite';

/**
 * The demo imports `kenburnz` from the package *source* (not the built `dist`)
 * so editing `../src/*.ts` is reflected live with no rebuild step.
 */
export default defineConfig({
  resolve: {
    alias: {
      kenburnz: fileURLToPath(new URL('../src/index.ts', import.meta.url)),
    },
  },
  // Auto-open for the human `pnpm dev`; suppressed when the Playwright parity
  // test brings the server up (it sets KENBURNZ_NO_OPEN).
  server: { port: 5179, open: !process.env.KENBURNZ_NO_OPEN },
});
