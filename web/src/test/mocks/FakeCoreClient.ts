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
import { siRecommendation, siStructureDocument, siTaskCatalogue } from './fixtures';

export interface FakeCoreClientOptions {
  failLoad?: boolean;
  failRecommend?: boolean;
  failGenerate?: boolean;
  failDescribe?: boolean;
  failCompute?: boolean;
}

export class FakeCoreClient implements CoreClient {
  structureDocument: StructureDocument = siStructureDocument;
  recommendation: Recommendation = siRecommendation;
  failLoad = false;
  failRecommend = false;
  failGenerate = false;
  failDescribe = false;
  failCompute = false;
  calls = {
    loadStructure: 0,
    recommend: 0,
    generate: 0,
    compute: 0,
    describeTasks: 0,
  };
  /** Captured compute queries for asserting what was requested. */
  queries: RecordQuery[] = [];

  constructor(options: FakeCoreClientOptions = {}) {
    this.failLoad = options.failLoad ?? false;
    this.failRecommend = options.failRecommend ?? false;
    this.failGenerate = options.failGenerate ?? false;
    this.failDescribe = options.failDescribe ?? false;
    this.failCompute = options.failCompute ?? false;
  }

  async health(): Promise<void> {}

  async describeTasks(): Promise<TaskCatalogue> {
    this.calls.describeTasks += 1;
    if (this.failDescribe) {
      throw new Error('Could not describe tasks.');
    }
    return siTaskCatalogue;
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

  async compute(query: RecordQuery): Promise<RecordSet> {
    this.calls.compute += 1;
    this.queries.push(query);
    if (this.failCompute) {
      throw new Error('Record computation stage failed.');
    }
    const result: RecordSet = {};
    if (query.outputs.includes('analysis'))
      result.analysis = this.recommendation.analysis;
    if (query.outputs.includes('advice')) result.advice = this.recommendation.advice;
    if (query.outputs.includes('k_points')) {
      result.k_points = this.recommendation.k_points;
    }
    if (query.outputs.includes('selection')) {
      result.selection = this.recommendation.selection;
    }
    if (query.outputs.includes('generated_files')) {
      result.generated_files = this.recommendation.generated_files;
    }
    return result;
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
