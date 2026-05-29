import { fileURLToPath } from 'node:url';
import { defineConfig, devices } from '@playwright/test';

/**
 * Headed-browser parity tests for the two browser-only kenburnz surfaces
 * (WebCodecs export + CSS preview). **Local-only** — not run in CI, because the
 * webServer regenerates the Python reference renders (`misc/gen_preview_reference.py`),
 * which needs the `burns` Python package importable. Mirrors reelee-web's e2e
 * model.
 *
 * Run:  pnpm test:e2e            (headed, per the project decision)
 *       PW_HEADLESS=1 pnpm test:e2e   (headless; WebCodecs still works)
 *
 * First-time setup:  pnpm exec playwright install chromium
 */
const tsDir = fileURLToPath(new URL('.', import.meta.url));

export default defineConfig({
  testDir: './test-e2e',
  testMatch: '**/*.e2e.ts',
  fullyParallel: false,
  workers: 1,
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL: 'http://localhost:5180',
    // Headed by default (the project decision — a real, visible browser);
    // set PW_HEADLESS=1 to run headless (WebCodecs still works).
    headless: process.env.PW_HEADLESS === '1',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: {
    // Regenerate the Python reference, then serve the demo (which carries the
    // harness page) on a dedicated port.
    // `bash -c` (not `-lc`): a login shell would reset PATH and lose the
    // pyenv interpreter that has numpy + burns importable.
    command:
      'bash -c "python3 ../misc/gen_preview_reference.py && exec demo/node_modules/.bin/vite demo --port 5180 --strictPort"',
    cwd: tsDir,
    url: 'http://localhost:5180/harness.html',
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
    env: { KENBURNZ_NO_OPEN: '1' },
  },
});
