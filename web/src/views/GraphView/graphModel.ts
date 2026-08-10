// Pure, deep graph-presentation module.
//
// Turns a backend-owned `TaskGraphDescription` into a stable, renderable graph
// shape: dependency closure, selected-vs-required record classification, edges,
// and a deterministic layered layout. It is deliberately free of React Flow,
// HTTP, and Python implementation details — views only lay out the returned
// nodes and edges. Everything here is a pure function of the description, so it
// is fully unit-testable without a browser.

import type { StageDescription, TaskGraphDescription } from '../../client/types';

export type GraphNodeKind = 'selected' | 'required' | 'unused';

export interface GraphNode {
  /** Stable backend-owned record id (e.g. `analysis`). */
  id: string;
  /** Semantic stage name from the backend description. */
  name: string;
  description: string;
  kind: GraphNodeKind;
  x: number;
  y: number;
}

export interface GraphEdge {
  id: string;
  /** Dependency record id feeding a stage. */
  source: string;
  /** Stage output record id that consumes the source. */
  target: string;
}

export interface GraphPresentation {
  nodes: GraphNode[];
  edges: GraphEdge[];
  selectedIds: string[];
  requiredIds: string[];
}

const COLUMN_SPACING = 220;
const ROW_SPACING = 92;

function stageByOutput(task: TaskGraphDescription): Map<string, StageDescription> {
  return new Map(task.stages.map((stage) => [stage.output_record_id, stage]));
}

/**
 * Compute the transitive dependency closure of the requested output records:
 * every record that must be produced (selected outputs plus all of their
 * required inputs, recursively). Deterministic: the result is sorted.
 */
export function dependencyClosure(
  task: TaskGraphDescription,
  outputs: string[],
): string[] {
  const byOutput = stageByOutput(task);
  const needed = new Set<string>();
  const visit = (id: string): void => {
    if (needed.has(id)) return;
    needed.add(id);
    const stage = byOutput.get(id);
    if (stage) {
      for (const input of stage.input_record_ids) visit(input);
    }
  };
  for (const output of outputs) visit(output);
  return [...needed].sort();
}

/**
 * Build the full renderable graph for a task and the set of explicitly
 * selected output records. Nodes are classified as `selected` (the records the
 * operator asked for), `required` (dependency stages pulled in by the closure),
 * or `unused`. Layout is a deterministic dependency-depth layering: columns
 * advance with depth, rows stack records within a column.
 */
export function buildGraphPresentation(
  task: TaskGraphDescription,
  selectedIds: string[],
): GraphPresentation {
  const byOutput = stageByOutput(task);
  const allRecords = task.stages.map((stage) => stage.output_record_id);
  const closure = new Set(dependencyClosure(task, selectedIds));
  const requiredIds = [...closure].filter((id) => !selectedIds.includes(id)).sort();

  // Dependency depth: 0 for root records, one more than the deepest input.
  const depth = new Map<string, number>();
  const depthOf = (id: string): number => {
    const cached = depth.get(id);
    if (cached !== undefined) return cached;
    const stage = byOutput.get(id);
    let d = 0;
    if (stage && stage.input_record_ids.length > 0) {
      d = 1 + Math.max(...stage.input_record_ids.map(depthOf));
    }
    depth.set(id, d);
    return d;
  };
  for (const id of allRecords) depthOf(id);

  // Deterministic ordering: ascending depth, then record id.
  const ordered = [...allRecords].sort((a, b) => {
    const da = depthOf(a);
    const db = depthOf(b);
    return da - db || a.localeCompare(b);
  });

  const depths = [...new Set(ordered.map(depthOf))].sort((a, b) => a - b);
  const nodes: GraphNode[] = [];
  for (const d of depths) {
    const ids = ordered.filter((id) => depthOf(id) === d);
    ids.forEach((id, row) => {
      const stage = byOutput.get(id);
      nodes.push({
        id,
        name: stage?.name ?? id,
        description: stage?.description ?? '',
        kind: selectedIds.includes(id)
          ? 'selected'
          : closure.has(id)
            ? 'required'
            : 'unused',
        x: d * COLUMN_SPACING,
        y: row * ROW_SPACING,
      });
    });
  }

  // One edge per dependency input to its consuming stage.
  const edges: GraphEdge[] = [];
  for (const stage of task.stages) {
    for (const input of stage.input_record_ids) {
      edges.push({
        id: `${stage.output_record_id}<-${input}`,
        source: input,
        target: stage.output_record_id,
      });
    }
  }

  return { nodes, edges, selectedIds: [...selectedIds], requiredIds };
}
