import { useId, useState } from "react";
import { ActionIcon, Button, Group, List, Stack, Text } from "@mantine/core";
import { Info } from "lucide-react";

import type { BlockingFinding } from "../api/coreClient";
import { currentFindings } from "../workspace/pipelineStatus";
import { useWorkspace, useWorkspaceSnapshot } from "../workspace/useWorkspace";

type OverridePatch = BlockingFinding["remedies"][number];

/** A remedy's button label, e.g. `Apply occupations = smearing`; a key the
 * patch clears reads `automatic`. */
function remedyLabel(remedy: OverridePatch): string {
  const changes = Object.entries(remedy).map(
    ([key, value]) =>
      `${key} = ${value === null ? "automatic" : displayed(value)}`,
  );
  return `Apply ${changes.join(", ")}`;
}

function displayed(value: unknown): string {
  return typeof value === "string" ? value : JSON.stringify(value);
}

/** A remedy button grows to as many lines as its label needs: a label such as
 * `Apply spin_polarized = true, occupations = smearing` is wider than a note
 * under a control in a column at its 20rem floor, which would otherwise cut
 * off the button and the message above it. The theme's 44 px minimum height
 * still applies, so one line, or two, keep that height. */
const WRAPPING_BUTTON_STYLES = {
  root: {
    display: "inline-flex",
    alignItems: "center",
    height: "auto",
    paddingBlock: "0.3125rem",
  },
  label: { whiteSpace: "normal", lineHeight: 1.3 },
} as const;

/** One button per remedy of `finding` (#151). A click applies that override
 * patch to the draft, a `null` value clearing its key back to automatic, and
 * the draft's recommendation is recomputed. */
export function RemedyButtons({
  finding,
}: {
  readonly finding: BlockingFinding;
}) {
  const workspace = useWorkspace();
  if (finding.remedies.length === 0) return null;
  return (
    <Group gap="xs">
      {finding.remedies.map((remedy) => {
        const label = remedyLabel(remedy);
        return (
          <Button
            key={label}
            size="xs"
            variant="light"
            styles={WRAPPING_BUTTON_STYLES}
            onClick={() =>
              void workspace.dispatch({
                type: "draft.patch",
                overrides: Object.fromEntries(
                  Object.entries(remedy).map(([key, value]) => [
                    key,
                    value ?? undefined,
                  ]),
                ),
              })
            }
          >
            {label}
          </Button>
        );
      })}
    </Group>
  );
}

function findingKey(finding: BlockingFinding): string {
  return JSON.stringify([finding.code, finding.message]);
}

/** `findings` as a list, each its summary, a toggle that shows its full
 * message in place, and its remedy buttons: the failure banner's and the
 * Bundle card's account of why no input files exist, the one place a
 * finding's remedies are offered (#223). */
export function FindingList({
  findings,
}: {
  readonly findings: readonly BlockingFinding[];
}) {
  return (
    <List size="sm" spacing="xs">
      {findings.map((finding) => (
        <List.Item key={findingKey(finding)}>
          <FindingEntry finding={finding} />
        </List.Item>
      ))}
    </List>
  );
}

function FindingEntry({ finding }: { readonly finding: BlockingFinding }) {
  const [expanded, setExpanded] = useState(false);
  const detailsId = useId();
  return (
    <Stack gap={4} align="flex-start">
      <Group gap={4} wrap="nowrap" align="flex-start">
        <Text size="sm">{finding.summary}</Text>
        <ActionIcon
          variant="subtle"
          color="gray"
          aria-expanded={expanded}
          aria-controls={detailsId}
          aria-label={expanded ? "Hide the details" : "Show the details"}
          title={expanded ? "Hide the details" : "Show the details"}
          onClick={() => {
            setExpanded(!expanded);
          }}
        >
          <Info aria-hidden="true" size={16} />
        </ActionIcon>
      </Group>
      <Text id={detailsId} size="xs" hidden={!expanded}>
        {finding.message}
      </Text>
      <RemedyButtons finding={finding} />
    </Stack>
  );
}

/** One line under the control of setting or fact `field` while a finding of
 * the current draft concerns it, pointing to the Bundle card, which holds
 * the findings and their remedies (#223); nothing when none does. */
export function FindingNotes({ field }: { readonly field: string }) {
  const snapshot = useWorkspaceSnapshot();
  const findings = currentFindings(snapshot).filter((finding) =>
    finding.fields.includes(field),
  );
  if (findings.length === 0) return null;
  return (
    <Text
      size="xs"
      c="red"
      role="note"
      aria-label={`Blocks input generation: ${field}`}
    >
      {findings.every((finding) => finding.remedies.length > 0)
        ? "Needs confirmation — see Bundle"
        : "Blocks input generation — see Bundle"}
    </Text>
  );
}
