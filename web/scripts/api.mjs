// Generates the committed TypeScript client contract from the live FastAPI
// OpenAPI document, or verifies the committed contract has no drift.
//
//   node scripts/api.mjs            # write scripts/openapi.json + src/client/generated/dto.ts
//   node scripts/api.mjs --verify   # fail unless regeneration leaves no diff
//
// The generated dto.ts is committed and never hand-edited. `--verify` renders
// into a temporary directory and compares bytes with the committed files, so a
// stale contract fails CI instead of silently passing.

import { execFileSync } from 'node:child_process';
import { existsSync, mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const monorepoRoot = resolve(here, '..', '..'); // goldilocks-core repo root (uv cwd)
const webRoot = resolve(here, '..'); // web/ (src, node_modules)
const openApiCommitted = join(here, 'openapi.json');
const dtoCommitted = join(webRoot, 'src', 'client', 'generated', 'dto.ts');
const verify = process.argv.includes('--verify');

function run(cmd, args, opts) {
  return execFileSync(cmd, args, {
    stdio: ['ignore', 'pipe', 'inherit'],
    encoding: 'utf8',
    ...opts,
  });
}

function exportOpenApi(outFile) {
  // Run from the monorepo root so `uv` resolves goldilocks-core with its http extra.
  run('uv', ['run', 'python', 'web/scripts/export_openapi.py', outFile], {
    cwd: monorepoRoot,
  });
}

function generateDto(openApiFile, dtoFile) {
  const bin = join(webRoot, 'node_modules', '.bin', 'openapi-typescript');
  run(bin, [openApiFile, '-o', dtoFile]);
}

if (!verify) {
  exportOpenApi(openApiCommitted);
  generateDto(openApiCommitted, dtoCommitted);
  console.log('generated scripts/openapi.json and src/client/generated/dto.ts');
} else {
  const tmp = mkdtempSync(join(tmpdir(), 'goldilocks-api-'));
  try {
    const openApiTmp = join(tmp, 'openapi.json');
    const dtoTmp = join(tmp, 'dto.ts');
    exportOpenApi(openApiTmp);
    generateDto(openApiTmp, dtoTmp);
    const sameOpen =
      existsSync(openApiCommitted) &&
      readFileSync(openApiTmp, 'utf8') === readFileSync(openApiCommitted, 'utf8');
    const sameDto =
      existsSync(dtoCommitted) &&
      readFileSync(dtoTmp, 'utf8') === readFileSync(dtoCommitted, 'utf8');
    if (!sameOpen) {
      console.error(
        'DRIFT: scripts/openapi.json is stale. Run `npm run generate:api`.',
      );
      process.exit(1);
    }
    if (!sameDto) {
      console.error(
        'DRIFT: src/client/generated/dto.ts is stale. Run `npm run generate:api`.',
      );
      process.exit(1);
    }
    console.log('generated contract is clean');
  } finally {
    rmSync(tmp, { recursive: true, force: true });
  }
}
