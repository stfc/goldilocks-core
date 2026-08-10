// Type-level contract guard: the hand-written domain types in `client/types.ts`
// must stay structurally compatible with the generated OpenAPI schemas.
//
// These assertions carry no runtime cost — they are erased at compile time — and
// are checked by `tsc` during `npm run typecheck` and `npm run build`. They catch
// the class of drift the HTTP adapter's `as` casts cannot: a backend schema change
// regenerates `dto.ts` silently, but if the Workbench domain type no longer fits
// the wire schema this file stops compiling.
//
// Direction: each domain type must be assignable to its generated counterpart.
// This guards the dangerous case where Core adds or tightens a *required* field
// the Workbench forgot to model (e.g. a required advice field silently dropped by
// a presenter). Removal of a backend field the domain still references surfaces
// at the HTTP adapter as a narrower generated type, which the domain's own use
// of it exercises.
//
// Only the adapter may import `client/generated`; this file is the sole exception
// and exists precisely to tie the two contracts together.

import type { components } from '../../client/generated/dto';
import type * as domain from '../../client/types';

type IsAssignable<Source, Target> = [Source] extends [Target] ? true : false;
type Expect<T extends true> = T;
type Schema = components['schemas'];

// Structures
export type _StructureSource = Expect<
  IsAssignable<domain.StructureSource, Schema['StructureSource']>
>;
export type _StructureDocument = Expect<
  IsAssignable<domain.StructureDocument, Schema['StructureDocumentModel']>
>;

// Calculation request
export type _Intent = Expect<IsAssignable<domain.Intent, Schema['Intent']>>;
export type _Hints = Expect<IsAssignable<domain.Hints, Schema['Hints']>>;
export type _ComputationRequest = Expect<
  IsAssignable<domain.ComputationRequest, Schema['ComputationRequest']>
>;
export type _RecordQuery = Expect<
  IsAssignable<domain.RecordQuery, Schema['RecordQuery']>
>;

// Recommendation records
export type _Provenance = Expect<
  IsAssignable<domain.Provenance, Schema['ProvenanceModel']>
>;
export type _Analysis = Expect<IsAssignable<domain.Analysis, Schema['AnalysisModel']>>;
export type _Advice = Expect<IsAssignable<domain.Advice, Schema['AdviceModel']>>;
export type _KPointSelection = Expect<
  IsAssignable<domain.KPointSelection, Schema['KPointSelectionModel']>
>;
export type _Selection = Expect<
  IsAssignable<domain.Selection, Schema['SelectionModel']>
>;
export type _GeneratedFile = Expect<
  IsAssignable<domain.GeneratedFile, Schema['GeneratedFileModel']>
>;
export type _Recommendation = Expect<
  IsAssignable<domain.Recommendation, Schema['CoreResultResponse']>
>;
export type _RecordSet = Expect<
  IsAssignable<domain.RecordSet, Schema['RecordSetResponse']>
>;

// Task graph descriptions
export type _TaskGraphDescription = Expect<
  IsAssignable<domain.TaskGraphDescription, Schema['TaskGraphDescriptionModel']>
>;
export type _TaskCatalogue = Expect<
  IsAssignable<domain.TaskCatalogue, Schema['TaskCatalogueModel']>
>;
