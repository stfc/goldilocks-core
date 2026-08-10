// The HTTP adapter for the Core seam.
//
// This is the ONLY module that knows the generated contract, fetch/OpenAPI,
// routes, status codes, serialisation, or raw JSON. It maps every response —
// success or failure — to the domain types and `CoreFailure` shape defined at
// the seam, so nothing above it touches transport concepts.
//
// Backend schemas are generated with Pydantic `extra="allow"`, which gives the
// generated types index signatures and wider field types than the Workbench
// domain types. The casts below are therefore the adapter's one job: they bridge
// the generated wire types and the domain vocabulary at the seam, and the
// `verify:api` drift check keeps the two aligned as the backend evolves.

import createClient from 'openapi-fetch';
import type { components, paths } from './generated/dto';
import { localFailure, toCoreFailure } from './failures';
import type { CoreClient } from './CoreClient';
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

type ApiClient = ReturnType<typeof createClient<paths>>;
type Schemas = components['schemas'];

export class HttpCoreClient implements CoreClient {
  private readonly api: ApiClient;

  constructor(baseUrl = '') {
    this.api = createClient<paths>({ baseUrl });
  }

  async health(): Promise<void> {
    await this.unwrap<void>(this.api.GET('/health'));
  }

  describeTasks(): Promise<TaskCatalogue> {
    return this.unwrap<TaskCatalogue>(this.api.GET('/tasks'));
  }

  loadStructure(source: StructureSource): Promise<StructureDocument> {
    return this.unwrap<StructureDocument>(
      this.api.POST('/structure/load', { body: source as Schemas['StructureSource'] }),
    );
  }

  recommend(request: ComputationRequest): Promise<Recommendation> {
    return this.unwrap<Recommendation>(
      this.api.POST('/recommend', { body: toComputationRequest(request) }),
    );
  }

  compute(query: RecordQuery): Promise<RecordSet> {
    return this.unwrap<RecordSet>(
      this.api.POST('/compute', {
        body: {
          structure: query.structure as Schemas['StructureSource'],
          outputs: query.outputs as Schemas['RecordQuery']['outputs'],
          intent: query.intent as Schemas['Intent'] | null | undefined,
          hints: query.hints as Schemas['Hints'] | null | undefined,
        },
      }),
    );
  }

  generate(request: ComputationRequest): Promise<GeneratedInputSet> {
    return this.unwrap<GeneratedInputSet>(
      this.api.POST('/generate', { body: toComputationRequest(request) }),
    );
  }

  private async unwrap<T>(
    promise: Promise<{ data?: unknown; error?: unknown }>,
  ): Promise<T> {
    let result: { data?: unknown; error?: unknown };
    try {
      result = await promise;
    } catch (error) {
      throw toCoreFailure(error);
    }
    if (result.error) {
      throw toCoreFailure(result.error);
    }
    if (result.data === undefined) {
      throw localFailure('unavailable', 'Core returned an empty response.');
    }
    return result.data as T;
  }
}

/** Bridge the Workbench request vocabulary onto the wire schema. */
function toComputationRequest(
  request: ComputationRequest,
): Schemas['ComputationRequest'] {
  return {
    structure: request.structure as Schemas['StructureSource'],
    intent: request.intent as Schemas['Intent'] | null | undefined,
    hints: request.hints as Schemas['Hints'] | null | undefined,
  };
}
