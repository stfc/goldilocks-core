// Configurable fake CoreClient for tests. Returns known-good fixtures and
// records call counts; failure flags let tests exercise failure containment.

import type { CoreClient } from '../../client/CoreClient';
import type {
  ComputationRequest,
  GeneratedInputSet,
  RecordQuery,
  RecordSet,
  Recommendation,
  StructureDocument,
  StructureSource,
  TaskCatalogue,
} from '../../client/types';
import { siRecommendation, siStructureDocument } from './fixtures';

export interface FakeCoreClientOptions {
  failLoad?: boolean;
  failRecommend?: boolean;
  failGenerate?: boolean;
}

export class FakeCoreClient implements CoreClient {
  structureDocument: StructureDocument = siStructureDocument;
  recommendation: Recommendation = siRecommendation;
  failLoad = false;
  failRecommend = false;
  failGenerate = false;
  calls = { loadStructure: 0, recommend: 0, generate: 0, compute: 0 };

  constructor(options: FakeCoreClientOptions = {}) {
    this.failLoad = options.failLoad ?? false;
    this.failRecommend = options.failRecommend ?? false;
    this.failGenerate = options.failGenerate ?? false;
  }

  async health(): Promise<void> {}

  async describeTasks(): Promise<TaskCatalogue> {
    return { tasks: [] };
  }

  async loadStructure(source: StructureSource): Promise<StructureDocument> {
    this.calls.loadStructure += 1;
    if (this.failLoad || !source.content.trim()) {
      throw new Error('Could not parse structure.');
    }
    return this.structureDocument;
  }

  async recommend(_request: ComputationRequest): Promise<Recommendation> {
    this.calls.recommend += 1;
    if (this.failRecommend) {
      throw new Error('Recommendation stage failed.');
    }
    return this.recommendation;
  }

  async compute(_query: RecordQuery): Promise<RecordSet> {
    this.calls.compute += 1;
    return { analysis: this.recommendation.analysis };
  }

  async generate(_request: ComputationRequest): Promise<GeneratedInputSet> {
    this.calls.generate += 1;
    if (this.failGenerate) {
      throw new Error('Generation stage failed.');
    }
    return {
      ...this.recommendation,
      generated_files: [
        {
          path: 'inputs/qe.in',
          content: '&control\n  calculation="scf"\n/\n',
          role: 'input',
        },
      ],
    };
  }
}
