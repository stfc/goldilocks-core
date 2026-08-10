// Browser-side input archive construction.
//
// Turns generated inputs plus manifest data into one named ZIP blob. Uses
// `fflate` and never touches server paths: the archive is assembled purely
// from content returned by Core and the structure the user supplied.

import { strToU8, zipSync, type Zippable } from 'fflate';
import type {
  ComputationRequest,
  GeneratedFile,
  Recommendation,
  StructureDocument,
  StructureSource,
} from '../client/types';

export interface ManifestMeta {
  /** Core version, when Core reports one; omitted rather than invented. */
  coreVersion?: string;
  model?: string;
  generatedBy: 'goldilocks-workbench';
  createdAt: string;
}

function sourceReason(p: {
  source: string;
  reason: string;
  confidence?: number | null;
  data_source?: string | null;
}): { source: string; reason: string } {
  return { source: p.source, reason: p.reason };
}

/**
 * Collect a model identifier from the recommendation's actual provenance.
 *
 * The k-point selection is the model-backed record in this pipeline; its
 * provenance ``data_source`` names the model when one produced it, and its
 * ``details`` may carry an explicit model key. Nothing here is invented or
 * hardcoded — if the recommendation carries no model identity, this is
 * undefined and the manifest records ``model: null``.
 */
function collectModelIdentity(rec: Recommendation): string | undefined {
  const kp = rec.k_points?.provenance;
  const dataSource = kp?.data_source?.trim();
  if (dataSource) return dataSource;
  if (kp?.details && typeof kp.details === 'object') {
    const details = kp.details as Record<string, unknown>;
    const model = details['model'] ?? details['model_name'];
    if (typeof model === 'string' && model.trim()) return model.trim();
  }
  return undefined;
}

/** The archive's downloadable filename, named after the structure formula. */
export function inputArchiveName(structure: StructureDocument): string {
  const base = structure.reduced_formula || structure.formula || 'goldilocks-inputs';
  return `${base}-inputs.zip`;
}

export interface InputArchiveInput {
  files: GeneratedFile[];
  structure: StructureDocument;
  request: ComputationRequest;
  recommendation: Recommendation;
  meta: ManifestMeta;
}

const ARCHIVE_VERSION = '1';

function originalStructureEntry(source: StructureSource): {
  name: string;
  content: string;
} {
  if (source.format === 'poscar') {
    return { name: 'structure.vasp', content: source.content };
  }
  return { name: 'structure.cif', content: source.content };
}

function manifest(input: InputArchiveInput): Record<string, unknown> {
  const { recommendation: rec, request, structure, meta } = input;
  return {
    schema: 'goldilocks/manifest',
    version: ARCHIVE_VERSION,
    generated_by: meta.generatedBy,
    created_at: meta.createdAt,
    core_version: meta.coreVersion,
    model: meta.model ?? collectModelIdentity(input.recommendation) ?? null,
    request: {
      intent: rec.intent,
      hints: request.hints ?? {},
    },
    records: {
      analysis: rec.analysis,
      advice: rec.advice,
      k_points: rec.k_points,
      selection: rec.selection,
    },
    provenance: {
      smearing: sourceReason(rec.advice.smearing.provenance),
      magnetism: sourceReason(rec.advice.magnetism.provenance),
      spin_orbit: sourceReason(rec.advice.spin_orbit.provenance),
      pseudopotentials: sourceReason(rec.advice.pseudopotentials.provenance),
      convergence: sourceReason(rec.advice.convergence.provenance),
      vdw: sourceReason(rec.advice.vdw.provenance),
      k_points: sourceReason(rec.k_points.provenance),
      selection: rec.selection.pseudopotentials.map((p) => ({
        element: p.element,
        filename: p.filename,
        source: p.provenance.source,
        reason: p.provenance.reason,
      })),
    },
    warnings: rec.warnings,
    structure: {
      formula: structure.formula,
      reduced_formula: structure.reduced_formula,
      site_count: structure.sites.length,
    },
  };
}

/**
 * Build the downloadable input archive as a ZIP `Blob`. Entries: generated
 * input files, the original structure, and a reproducibility manifest.
 *
 * Generated entry names that collide with a reserved entry (the manifest or
 * the original structure) or with one another are rejected loudly rather than
 * silently overwriting — a corrupted archive must not ship silently.
 */
export function buildInputArchive(input: InputArchiveInput): Blob {
  const original = originalStructureEntry(input.request.structure);
  const reserved = new Set(['goldilocks.json', original.name]);
  const seen = new Set<string>();
  for (const file of input.files) {
    if (reserved.has(file.path)) {
      throw new Error(`Archive entry ${file.path!} collides with a reserved entry.`);
    }
    if (seen.has(file.path)) {
      throw new Error(`Duplicate archive entry: ${file.path!}.`);
    }
    seen.add(file.path);
  }

  const entries: Zippable = {
    'goldilocks.json': strToU8(JSON.stringify(manifest(input), null, 2)),
    [original.name]: strToU8(original.content),
  };
  for (const file of input.files) {
    entries[file.path] = strToU8(file.content);
  }

  const bytes = zipSync(entries, { level: 6 });
  return new Blob([bytes], { type: 'application/zip' });
}

/**
 * Build and trigger a browser download of the formula-named input archive.
 * Returns the filename used, so tests can assert it without a real download.
 */
export function downloadInputArchive(input: InputArchiveInput): string {
  const blob = buildInputArchive(input);
  const name = inputArchiveName(input.structure);
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = name;
  anchor.rel = 'noopener';
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  // Firefox can begin the download asynchronously after the click returns;
  // revoking the object URL immediately can race it, so release it shortly.
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
  return name;
}
