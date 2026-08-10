import { describe, expect, it } from 'vitest';
import type { TaskGraphDescription } from '../../client/types';
import {
  buildGraphPresentation,
  dependencyClosure,
} from '../../views/GraphView/graphModel';
import { siTaskCatalogue } from '../mocks/fixtures';

const task: TaskGraphDescription = siTaskCatalogue.tasks[0];

describe('dependencyClosure', () => {
  it('returns the selected record plus every transitive required input', () => {
    const closure = dependencyClosure(task, ['analysis', 'k_points']);
    expect(closure).toEqual(
      expect.arrayContaining(['analysis', 'k_points', 'structure']),
    );
    // The selection record is not required by analysis/k-points.
    expect(closure).not.toContain('selection');
    expect(closure).not.toContain('advice');
  });

  it('walks the full dependency chain for the selection record', () => {
    // selection depends on structure and advice; advice depends on analysis;
    // analysis depends on structure.
    const closure = dependencyClosure(task, ['selection']);
    expect(closure).toEqual(
      expect.arrayContaining(['selection', 'structure', 'advice', 'analysis']),
    );
    expect(closure).not.toContain('k_points');
  });

  it('includes every transitive dependency, not just direct inputs', () => {
    // generated_files depends on advice -> analysis -> structure and on
    // selection -> advice and k_points -> structure.
    const closure = dependencyClosure(task, ['generated_files']);
    for (const id of [
      'generated_files',
      'structure',
      'analysis',
      'advice',
      'selection',
      'k_points',
    ]) {
      expect(closure).toContain(id);
    }
  });

  it('is deterministic regardless of the requested output order', () => {
    const a = dependencyClosure(task, ['k_points', 'analysis']);
    const b = dependencyClosure(task, ['analysis', 'k_points']);
    expect(a).toEqual(b);
  });

  it('is a pure function that does not mutate the task', () => {
    const snapshot = JSON.stringify(task);
    dependencyClosure(task, ['analysis']);
    expect(JSON.stringify(task)).toBe(snapshot);
  });
});

describe('buildGraphPresentation', () => {
  it('marks explicitly selected records, required dependencies, and unused records', () => {
    const presentation = buildGraphPresentation(task, ['analysis', 'k_points']);

    const kind = (id: string) => presentation.nodes.find((n) => n.id === id)?.kind;
    expect(kind('analysis')).toBe('selected');
    expect(kind('k_points')).toBe('selected');
    expect(kind('structure')).toBe('required');
    expect(kind('selection')).toBe('unused');
    expect(kind('advice')).toBe('unused');
    expect(kind('generated_files')).toBe('unused');
  });

  it('distinguishes required dependency records from the selected outputs', () => {
    const presentation = buildGraphPresentation(task, ['analysis', 'k_points']);
    expect(presentation.selectedIds).toEqual(
      expect.arrayContaining(['analysis', 'k_points']),
    );
    expect(presentation.requiredIds).toContain('structure');
    expect(presentation.requiredIds).not.toContain('analysis');
    expect(presentation.requiredIds).not.toContain('k_points');
  });

  it('reports the full closure for required dependency records', () => {
    const presentation = buildGraphPresentation(task, ['selection']);
    // advice is a required dependency even though it is not selected.
    expect(presentation.requiredIds).toContain('advice');
    expect(presentation.requiredIds).toContain('analysis');
    expect(presentation.requiredIds).toContain('structure');
  });

  it('derives one edge per dependency input to its consuming stage', () => {
    const presentation = buildGraphPresentation(task, ['analysis']);
    const edges = presentation.edges;
    expect(edges).toContainEqual(
      expect.objectContaining({ source: 'structure', target: 'analysis' }),
    );
    expect(edges).toContainEqual(
      expect.objectContaining({ source: 'structure', target: 'k_points' }),
    );
    expect(edges).toContainEqual(
      expect.objectContaining({ source: 'advice', target: 'selection' }),
    );
    // Every edge id is unique.
    const ids = edges.map((e) => e.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it('produces a deterministic layout for identical input', () => {
    const a = buildGraphPresentation(task, ['analysis']);
    const b = buildGraphPresentation(task, ['analysis']);
    expect(a.nodes.map((n) => [n.id, n.x, n.y])).toEqual(
      b.nodes.map((n) => [n.id, n.x, n.y]),
    );
  });

  it('lays nodes out in dependency-depth columns', () => {
    const presentation = buildGraphPresentation(task, ['generated_files']);
    const byId = new Map(presentation.nodes.map((n) => [n.id, n]));
    // structure is the root; generated_files is deepest.
    expect(byId.get('structure')?.x).toBeLessThan(byId.get('generated_files')?.x ?? 0);
  });

  it('names nodes from the backend stage descriptions, not implementation details', () => {
    const presentation = buildGraphPresentation(task, []);
    const analyze = presentation.nodes.find((n) => n.id === 'analysis');
    expect(analyze?.name).toBe('Analyze');
    // No Python class names or callable names leak through.
    const raw = JSON.stringify(presentation.nodes);
    expect(raw).not.toContain('StructureAnalysisRecord');
    expect(raw).not.toContain('callable');
  });

  it('handles an empty selection as an all-unused graph', () => {
    const presentation = buildGraphPresentation(task, []);
    expect(presentation.selectedIds).toEqual([]);
    expect(presentation.requiredIds).toEqual([]);
    expect(presentation.nodes.every((n) => n.kind === 'unused')).toBe(true);
  });
});
