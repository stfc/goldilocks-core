import { unzipSync } from "fflate";

import type { ArchiveDownload } from "../api/coreClient";

/** The request a bundle answers -- `bundle.py`'s `RequestIdentity`
 * (#176). `sha256`/`size_bytes` are those of the submitted structure text,
 * `null` for a structure built in memory. */
export interface ManifestRequest {
  readonly code: string;
  readonly task: string;
  readonly hpc: string;
  readonly core_version: string;
  readonly overrides: Readonly<Record<string, unknown>>;
  readonly structure: {
    readonly name: string;
    readonly format: string;
    readonly sha256: string | null;
    readonly size_bytes: number | null;
  };
}

/** Mirrors `goldilocks.json`'s shape, written by `bundle.py`'s
 * `bundle_files` -- the manifest v1's combined /compute response used
 * to hand back as JSON is now only ever found inside the downloaded
 * archive itself (v2's `/run` never returns JSON and a file's bytes in
 * the same response). */
export interface InputManifest {
  readonly schema_version: number;
  readonly request: ManifestRequest;
  readonly records: Readonly<Record<string, unknown>>;
  readonly warnings: readonly unknown[];
  readonly citations: readonly string[];
  /** The task's steps in run order, each with the input files it reads
   * (#222). */
  readonly steps: readonly ManifestStep[];
  readonly files: Readonly<
    Record<
      string,
      {
        readonly role: string;
        readonly sha256: string;
        readonly size_bytes: number;
      }
    >
  >;
}

export interface ManifestStep {
  readonly name: string;
  readonly files: readonly string[];
}

export interface ArchiveFile {
  readonly path: string;
  readonly content: string;
}

export interface ArchiveContents {
  readonly manifest: InputManifest | null;
  readonly files: readonly ArchiveFile[];
}

/** Unzips a downloaded archive client-side to recover per-file text and
 * `goldilocks.json`'s manifest -- purely a presentation concern (the
 * API client only ever hands back the raw zip bytes it was given). */
export async function unzipArchive(
  archive: ArchiveDownload,
): Promise<ArchiveContents> {
  const entries = unzipSync(new Uint8Array(await archive.blob.arrayBuffer()));
  const decoder = new TextDecoder("utf-8");
  const files: ArchiveFile[] = [];
  let manifest: InputManifest | null = null;
  for (const [path, bytes] of Object.entries(entries)) {
    const content = decoder.decode(bytes);
    if (path === "goldilocks.json") {
      manifest = parseManifest(content);
    }
    files.push({ path, content });
  }
  return { manifest, files };
}

function parseManifest(content: string): InputManifest | null {
  try {
    const parsed: unknown = JSON.parse(content);
    return isManifest(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

function isManifest(value: unknown): value is InputManifest {
  return (
    typeof value === "object" &&
    value !== null &&
    "files" in value &&
    typeof value.files === "object" &&
    "steps" in value &&
    Array.isArray(value.steps)
  );
}

export function artifactMetadata(
  manifest: InputManifest | null,
  filename: string,
): { sha256: string | undefined; size_bytes: number | undefined } | undefined {
  const descriptor = manifest?.files[filename];
  return descriptor === undefined
    ? undefined
    : { sha256: descriptor.sha256, size_bytes: descriptor.size_bytes };
}
