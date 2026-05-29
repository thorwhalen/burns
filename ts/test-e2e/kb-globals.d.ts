/**
 * Ambient typing for the `window.kb` parity harness (set up by
 * `demo/src/harness.ts`) so the Playwright specs typecheck their
 * `page.evaluate` callbacks.
 */
export {};

interface KbBox {
  x0: number;
  y0: number;
  x1: number;
  y1: number;
}
interface KbExportInfo {
  size: number;
  type: string;
  frameCount: number;
  width: number;
  height: number;
  codec: string;
}

declare global {
  interface Window {
    kb?: {
      manifest: unknown;
      webCodecs: boolean;
      frameDiff(scenarioId: string, t: number, file: string): Promise<number>;
      cssWindowPx(scenarioId: string, t: number): KbBox;
      exportWebm(scenarioId: string): Promise<KbExportInfo>;
    };
    kbReady: Promise<void>;
  }
}
