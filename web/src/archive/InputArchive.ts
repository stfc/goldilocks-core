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
  coreVersion: string;
  model?: string;
  generatedBy: 'goldilocks-workbench';
  createdAt: string;
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
    model: meta.model ?? null,
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
      k_points: {
        source: rec.k_points.provenance.source,
        reason: rec.k_points.provenance.reason,
      },
      pseudopotentials: rec.selection.pseudopotentials.map((p) => ({
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
 */
export function buildInputArchive(input: InputArchiveInput): Blob {
  const original = originalStructureEntry(input.request.structure);

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
