// The sole seam to Core.
//
// Every Workbench module that needs backend data depends on this interface,
// never on the HTTP transport or generated client internals. Only adapters
// (`HttpCoreClient`) and fakes know HTTP paths, generated schemas, status
// codes, serialisation, or raw JSON. Failures cross the seam as `CoreFailure`.

import type {
  ComputationRequest,
  GeneratedInputSet,
  RecordQuery,
  RecordSet,
  Recommendation,
  StructureDocument,
  StructureSource,
  TaskCatalogue,
} from './types';

export interface CoreClient {
  /** Report process liveness. */
  health(): Promise<void>;
  /** Describe every registered Core task with stable identifiers. */
  describeTasks(): Promise<TaskCatalogue>;
  /** Validate and normalise inline structure content into a Structure Document. */
  loadStructure(source: StructureSource): Promise<StructureDocument>;
  /** Run the recommend preset and return its records. */
  recommend(request: ComputationRequest): Promise<Recommendation>;
  /** Compute only the requested record types. */
  compute(query: RecordQuery): Promise<RecordSet>;
  /** Run the generate preset and return in-memory generated input contents. */
  generate(request: ComputationRequest): Promise<GeneratedInputSet>;
}
