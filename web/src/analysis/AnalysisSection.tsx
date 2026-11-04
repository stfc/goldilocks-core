import { Accordion, Stack, Text } from "@mantine/core";

import { OverrideControl } from "../controls/OverrideControl";
import { RecordAccordionItem } from "../review/RecordAccordionItem";
import { FindingNotes } from "../status/FindingNote";
import { analysisRecordNames } from "../workspace/recordGroups";
import { useWorkspace, useWorkspaceSnapshot } from "../workspace/useWorkspace";
import { FactSummary } from "./FactSummary";

/** goldilocks-core's own analysis tier only ever needs the structure --
 * `capabilities.facts` (is_metal/is_magnetic/needs_soc/needs_correlation)
 * plus the other records the response lays out in its analysis tier
 * (composition/geometry/symmetry, `RecordLayout.analysis`, #187). A fact
 * is an override control only when `Fact.overridable` says the core takes
 * a value for it; the others (needs_soc, advice that only a notice reads,
 * #186) are read-only `FactSummary`s. Every other record lives in the
 * Advisors card, next to the setting it belongs to or read-only after
 * them. A finding that concerns a fact is shown under it (#151). Rendered
 * inside `AnalysisCard`, which owns the "Analysis" heading -- this
 * component starts directly with its content. */
export function AnalysisSection() {
  const workspace = useWorkspace();
  const snapshot = useWorkspaceSnapshot();
  const { capabilities, draft, inspection, reviewed } = snapshot;
  if (capabilities === null || draft === null) {
    return null;
  }

  const disabled = snapshot.operation === "inspect" || inspection === null;
  const overrides = draft.overrides;

  const analysisOnlyRecords =
    reviewed === null
      ? []
      : analysisRecordNames(reviewed.layout, capabilities.facts).flatMap(
          (name) => {
            const field = reviewed.records[name];
            return field === undefined ? [] : [[name, field] as const];
          },
        );

  return (
    <Stack gap="sm">
      {capabilities.facts.length === 0 ? null : (
        <Stack gap="sm">
          {capabilities.facts.map((fact) => {
            const record = reviewed?.records[fact.key];
            return (
              <div key={fact.key}>
                {fact.overridable ? (
                  <OverrideControl
                    meta={{
                      key: fact.key,
                      type: fact.type,
                      enum: fact.values ?? undefined,
                      unit: null,
                      description: fact.description,
                    }}
                    value={overrides[fact.key]}
                    resolvedValue={
                      record?.status === "resolved" ? record.value : undefined
                    }
                    source={
                      record?.status === "resolved" ? record.source : undefined
                    }
                    disabled={disabled}
                    onChange={(value) => {
                      void workspace.dispatch({
                        type: "draft.patch",
                        overrides: { [fact.key]: value },
                      });
                    }}
                  />
                ) : (
                  <FactSummary fact={fact} record={record} />
                )}
                {record === undefined || record.status === "resolved" ? null : (
                  <Text
                    size="xs"
                    c={record.status === "blocked" ? "red" : "dimmed"}
                    mt={4}
                  >
                    {record.status === "blocked"
                      ? `Blocked — ${record.blocked_by ?? "an upstream field failed"}`
                      : `Unavailable — ${record.reason ?? "no reason given"}`}
                  </Text>
                )}
                <FindingNotes field={fact.key} />
              </div>
            );
          })}
        </Stack>
      )}
      {analysisOnlyRecords.length === 0 ? null : (
        <Accordion
          multiple
          transitionDuration={0}
          classNames={{ label: "workbench-accordion-label" }}
        >
          {analysisOnlyRecords.map(([key, field]) => (
            <RecordAccordionItem key={key} name={key} field={field} />
          ))}
        </Accordion>
      )}
    </Stack>
  );
}
