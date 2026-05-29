/**
 * Smoke E2E for the vanilla path-entry renderer (local-only, like parity.e2e).
 *
 * Drives the `/path-entry.html` demo in a real browser: the component mounts,
 * preset selection updates the emitted `BurnsPath`, dragging an interactive
 * crop rect mutates the keyframes, and Submit fires. It asserts *behaviour*
 * through the core's emitted value (mirrored into the demo's `#value` pre),
 * never internal DOM state. No paid API, no rendering backend.
 */

import { test, expect, type Page } from '@playwright/test';

async function emittedValue(page: Page): Promise<Record<string, unknown>> {
  const text = await page.locator('#value').textContent();
  const json = (text ?? '').replace(/^SUBMITTED\n\n/, '');
  return JSON.parse(json);
}

test.beforeEach(async ({ page }) => {
  await page.goto('/path-entry.html');
  // The component mounts after the source image probe loads.
  await expect(page.locator('.kb-pe')).toBeVisible();
  await expect(page.locator('.kb-pe-stage').first()).toBeVisible();
});

test('mounts and emits a valid initial BurnsPath', async ({ page }) => {
  const value = await emittedValue(page);
  expect(value['version']).toBe(1);
  expect(Array.isArray(value['keyframes'])).toBe(true);
  expect((value['keyframes'] as unknown[]).length).toBe(2);
  expect((value['meta'] as Record<string, unknown>)['preset_id']).toBe('zoom-in');
});

test('selecting a preset updates the emitted value', async ({ page }) => {
  await page.getByRole('button', { name: /Push in to/ }).click();
  const value = await emittedValue(page);
  expect((value['meta'] as Record<string, unknown>)['preset_id']).toBe('push-in-to');
});

test('dragging the interactive crop rect mutates the keyframes', async ({ page }) => {
  await page.getByRole('button', { name: /Push in to/ }).click();
  const before = await emittedValue(page);
  const beforeEnd = (before['keyframes'] as { rect: { x: number } }[])[1]!.rect.x;

  // The End pane carries the interactive rect for push-in-to.
  const rect = page.locator('.kb-pe-stage--end .kb-pe-rect');
  const box = await rect.boundingBox();
  expect(box).not.toBeNull();
  const cx = box!.x + box!.width / 2;
  const cy = box!.y + box!.height / 2;
  await page.mouse.move(cx, cy);
  await page.mouse.down();
  await page.mouse.move(cx - 40, cy, { steps: 6 });
  await page.mouse.up();

  const after = await emittedValue(page);
  const afterEnd = (after['keyframes'] as { rect: { x: number } }[])[1]!.rect.x;
  expect(afterEnd).not.toBeCloseTo(beforeEnd, 4);
});

test('keyboard nudge moves a focused rect', async ({ page }) => {
  await page.getByRole('button', { name: /Push in to/ }).click();
  const rect = page.locator('.kb-pe-stage--end .kb-pe-rect');
  await rect.focus();
  const before = (await emittedValue(page));
  const x0 = (before['keyframes'] as { rect: { x: number } }[])[1]!.rect.x;
  await rect.press('ArrowRight');
  await rect.press('ArrowRight');
  const after = await emittedValue(page);
  const x1 = (after['keyframes'] as { rect: { x: number } }[])[1]!.rect.x;
  expect(x1).toBeGreaterThan(x0);
});

test('Submit fires with the current value', async ({ page }) => {
  await page.getByRole('button', { name: 'Use this path' }).click();
  await expect(page.locator('#value')).toContainText('SUBMITTED');
});
