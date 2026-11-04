import type { Fact, RecordLayout, StepLayout } from "../api/coreClient";

/** Which card shows each record of a response, read from the response's
 * own `layout` (#187) rather than guessed from record names. The Analysis
 * card shows the analysis tier, what the structure alone decides; it shows
 * the facts as controls, so this lists the other records. */
export function analysisRecordNames(
  layout: RecordLayout,
  facts: readonly Fact[],
): string[] {
  const factKeys = new Set(facts.map((fact) => fact.key));
  return layout.analysis.filter((name) => !factKeys.has(name));
}

/** The advisor records the Advisors card shows read-only. */
export interface ReadOnlyAdvisorRecords {
  /** The system tier's, then the step's of a task with one step. */
  readonly ungrouped: readonly string[];
  /** Each step's of a task with more than one step, in run order; a step
   * with none to show is left out. */
  readonly steps: readonly StepLayout[];
}

/** The advisor records (the system tier and every step) that no setting
 * the Advisors card shows resolves into -- `shown` names the records that
 * those settings resolve into -- so it shows them read-only. */
export function readOnlyAdvisorRecords(
  layout: RecordLayout,
  shown: ReadonlySet<string>,
): ReadOnlyAdvisorRecords {
  const unshown = (names: readonly string[]) =>
    names.filter((name) => !shown.has(name));
  const steps = layout.steps.map((step) => ({
    name: step.name,
    records: unshown(step.records),
  }));
  const [onlyStep] = steps;
  if (steps.length === 1 && onlyStep !== undefined) {
    return {
      ungrouped: [...unshown(layout.system), ...onlyStep.records],
      steps: [],
    };
  }
  return {
    ungrouped: unshown(layout.system),
    steps: steps.filter((step) => step.records.length > 0),
  };
}
