# `burns` — Project Overview

*A starting point for anyone (human or AI agent) opening these documents for the first time.*

## What this project is

`burns` is a library and toolkit for rendering the **Ken Burns effect** — a pan-and-zoom animation over a still image — to a video (MP4 / WebM), GIF, or frame sequence, with an accompanying headless UI component for authoring the motion path.

The system spans **Python** (server-side, batch, programmatic) and **TypeScript** (client-side, browser, real-time preview). The two sides share a single serializable motion specification — the **`BurnsPath`** JSON — which is the single source of truth across languages, pinned by golden-vector parity tests.

## Documents in this folder, in reading order

1. **Research brief** — *Ken Burns Effect Libraries, Tooling, and API Design: A Research Brief.* Background on terminology, prior art (iMovie, Final Cut Pro, After Effects, FFmpeg `zoompan`, MoviePy, Remotion, GSAP), quality concerns (sub-pixel jitter), library comparison tables. Read this when you need vocabulary, parameter conventions, or to evaluate a backend choice.
2. **Architecture** — *Ken Burns: JS/TS-Only vs. Python+JS/TS Hybrid.* Where each pipeline stage runs (client vs. server), the contract between the Python and TypeScript implementations, the golden-vector test strategy for cross-language equivalence. Read this when you need to understand the system's seams, the wire format, or the rationale for the two-language design.
3. **Path-entry component spec** — *Headless Ken Burns Path-Entry Component.* Specification for the headless, schema-first UI component that authors a `BurnsPath` from user input. Read this when you are building or modifying the path-authoring component.

## Single source of truth

- **The `BurnsPath` JSON is the wire format.** Every backend (Python or TypeScript, server or browser, FFmpeg or WebCodecs) consumes the same JSON. The path-entry component emits the same JSON. Extensions add fields to the schema; they do not branch the shape per backend.
- **Spec documents are canonical.** If an issue, PR description, or comment disagrees with a spec, the spec wins. To change behaviour, update the spec first; implement second.
- **Golden vectors are the cross-language contract.** When the Python and TypeScript sides both implement the same operation (notably `BurnsPath.evaluate(t) → Rect` and the `Rect → output-pixels` mapping), they must agree against the shared fixture.

## Shared conventions

- **Vocabulary.** Use the terms established in the research brief's glossary. Notably: *crop rect* / *viewport*, *Start* / *End* rectangles (not "from" / "to"), *easing* (not "tween curve"), *keyframe*, *preset*. Don't invent terms when standard ones exist.
- **Coordinates.** Normalized `[0, 1]`, top-left origin, y-down. Resolution-independent.
- **Aspect-ratio invariant.** The crop rectangle's aspect ratio equals the **output frame's** aspect ratio — not the input image's.
- **Containment.** The crop rectangle stays inside the image: `0 ≤ x, y` and `x + w ≤ 1`, `y + h ≤ 1`.
- **Default easing is `ease-in-out`** — the professional / cinematic default. CSS-compatible easing strings are the cross-ecosystem lingua franca.
- **Zoom semantics are window-fraction**, not magnification. The user-facing parameter is the rectangle's size as a fraction of the image; magnification is a derived value reserved for backend translation layers.
