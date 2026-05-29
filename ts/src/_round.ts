/**
 * Python-compatible rounding (round-half-to-even, "banker's rounding").
 *
 * The Python reference implementation uses the built-in `round`, which rounds
 * a half exactly to the nearest *even* integer (`round(0.5) == 0`,
 * `round(2.5) == 2`). JavaScript's `Math.round` rounds a half toward `+∞`
 * (`Math.round(0.5) === 1`, `Math.round(2.5) === 3`). `Rect.toPixels` feeds the
 * exact-integer pixel boxes pinned by the golden vectors, so the two languages
 * must round identically — hence this helper rather than `Math.round`.
 */

/** Round to the nearest integer, ties to even — matches Python's `round(x)`. */
export function roundHalfToEven(x: number): number {
  const floor = Math.floor(x);
  const diff = x - floor;
  if (diff < 0.5) return floor;
  if (diff > 0.5) return floor + 1;
  // Exactly halfway (multiples of 0.5 are exactly representable): pick the even.
  return floor % 2 === 0 ? floor : floor + 1;
}

/**
 * Round to `ndigits` decimal places, ties to even — matches Python's
 * `round(x, ndigits)`. Used by the path generators (`kenBurnsPath`) so a
 * TS-authored path has the same keyframe coordinates as a Python-authored one.
 */
export function roundTo(x: number, ndigits: number): number {
  const factor = 10 ** ndigits;
  return roundHalfToEven(x * factor) / factor;
}
