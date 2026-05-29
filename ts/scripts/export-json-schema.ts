/**
 * Emit JSON Schema for the path-entry component's wire contract.
 *
 * The emitted {@link Value} (the `BurnsPath` JSON) is the single point of
 * contact with any rendering backend, so non-TS consumers (Python validation,
 * OpenAPI, etc.) need to validate it without depending on the zod source. This
 * script converts the zod schemas to JSON Schema and writes them under
 * `ts/schemas/` — committed artifacts, regenerated with `pnpm schema`.
 *
 * Run: `pnpm schema` (alias for `tsx scripts/export-json-schema.ts`).
 */

import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { z } from 'zod';
import { valueSchema, configSchema } from '../src/component/schema.js';

const here = dirname(fileURLToPath(import.meta.url));
const outDir = join(here, '..', 'schemas');
mkdirSync(outDir, { recursive: true });

function emit(name: string, schema: z.ZodType, title: string): void {
  const json = z.toJSONSchema(schema, { target: 'draft-2020-12' });
  const doc = { $schema: 'https://json-schema.org/draft/2020-12/schema', title, ...json };
  const path = join(outDir, `${name}.schema.json`);
  writeFileSync(path, JSON.stringify(doc, null, 2) + '\n');
  // eslint-disable-next-line no-console
  console.log(`wrote ${path}`);
}

emit('burns-path', valueSchema, 'BurnsPath (path-entry component output)');
emit('path-entry-config', configSchema, 'Ken Burns path-entry component config');
