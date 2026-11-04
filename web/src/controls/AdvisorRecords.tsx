import { useId } from "react";
import { Accordion, Stack, Title } from "@mantine/core";

import type { ResolvedField } from "../api/coreClient";
import { RecordAccordionItem } from "../review/RecordAccordionItem";

/** The advisor records `names` of `records`, read-only, as items of the
 * Advisors accordion they are rendered in: decisions no setting the card
 * shows resolves into, such as `pseudopotentials` or `symmetry_eff`
 * (#187). */
export function AdvisorRecordItems({
  names,
  records,
}: {
  readonly names: readonly string[];
  readonly records: Readonly<Record<string, ResolvedField>>;
}) {
  return (
    <>
      {names.map((name) => {
        const field = records[name];
        return field === undefined ? null : (
          <RecordAccordionItem key={name} name={name} field={field} />
        );
      })}
    </>
  );
}

/** The read-only records `names` of one step of a task with more than one
 * step, under a heading naming the step (`nscf step`, `bands step`,
 * `relax step`): a dos task's nscf decisions under their `nscf_` names, a
 * band task's bands-step path as `k_path` and its other decisions under
 * their `bands_` names, or a phonon task's decisions of one step, such as
 * its first step's `fft_grid` (#187, #118, #215). */
export function AdvisorStepRecords({
  step,
  names,
  records,
}: {
  readonly step: string;
  readonly names: readonly string[];
  readonly records: Readonly<Record<string, ResolvedField>>;
}) {
  const headingId = useId();
  return (
    <Stack component="section" gap="xs" aria-labelledby={headingId}>
      <Title order={3} id={headingId}>
        {step} step
      </Title>
      <Accordion
        multiple
        transitionDuration={0}
        classNames={{ label: "workbench-accordion-label" }}
      >
        <AdvisorRecordItems names={names} records={records} />
      </Accordion>
    </Stack>
  );
}
