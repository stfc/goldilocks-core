import {
  Alert,
  Button,
  Group,
  Loader,
  Paper,
  SimpleGrid,
  Stack,
  Text,
  Title,
} from "@mantine/core";
import { ArrowLeft, Download } from "lucide-react";

import type { ComputationResult } from "../api/coreClient";
import { useWorkspace, useWorkspaceSnapshot } from "../workspace/useWorkspace";
import { GeneratedInputReview } from "./GeneratedInputReview";
import { PseudopotentialReview } from "./PseudopotentialReview";
import { RecordReview } from "./RecordReview";
import "./ReviewPanel.css";

export function ReviewPanel({
  onShowStructure,
}: {
  readonly onShowStructure: () => void;
}) {
  const workspace = useWorkspace();
  const snapshot = useWorkspaceSnapshot();
  const result = snapshot.reviewed?.result ?? null;

  return (
    <Stack
      component="section"
      id="recommendation-panel"
      aria-label="Recommendation results"
      aria-busy={snapshot.operation === "compute"}
      p="md"
      gap="lg"
      miw={0}
    >
      <Group component="header" justify="space-between">
        <Title order={2}>Recommendation</Title>
        <Button
          variant="subtle"
          leftSection={<ArrowLeft aria-hidden="true" size={15} />}
          aria-label="Back to structure"
          onClick={onShowStructure}
        >
          Structure
        </Button>
      </Group>
      {result === null && (
        <Stack
          align="center"
          justify="center"
          mih={240}
          role={snapshot.operation === "compute" ? "status" : undefined}
        >
          {snapshot.operation === "compute" && <Loader size="sm" />}
          <Text fw={600}>
            {snapshot.operation === "compute"
              ? "Computing recommendation"
              : "No recommendation"}
          </Text>
        </Stack>
      )}
      {result !== null && (
        <>
          {snapshot.outOfDate && (
            <Alert
              role="status"
              aria-label="Recommendation notice"
              aria-live="polite"
              aria-atomic="true"
            >
              Your settings changed. Update the recommendation before
              downloading.
            </Alert>
          )}
          <Group justify="space-between">
            <Button
              rightSection={<Download aria-hidden="true" size={14} />}
              disabled={
                snapshot.reviewed?.archive == null ||
                snapshot.outOfDate ||
                snapshot.operation !== null
              }
              onClick={() =>
                void workspace.dispatch({ type: "review.download" })
              }
            >
              Download input files (.zip)
            </Button>
            {snapshot.lastDownload === null || snapshot.outOfDate ? null : (
              <Text
                size="sm"
                role="status"
                aria-label="Archive status"
                aria-live="polite"
              >
                {snapshot.lastDownload.filename} is ready
              </Text>
            )}
          </Group>
          <GeneratedInputReview result={result} />
          <RecommendationSummary result={result} />
          <PseudopotentialReview result={result} />
          <RecordReview result={result} />
          <Warnings result={result} />
        </>
      )}
    </Stack>
  );
}

function RecommendationSummary({
  result,
}: {
  readonly result: ComputationResult;
}) {
  const selected = result.records.selection?.pseudopotentials ?? [];
  const wavefunction = maximum(selected.map((item) => item.ecutwfc_ry));
  const density = maximum(selected.map((item) => item.ecutrho_ry));
  const intent = result.draft.intent;
  let spin = "Not returned";
  if (result.records.advice !== undefined) {
    spin = result.records.advice.magnetism.spin_polarized
      ? "Polarized"
      : "Unpolarized";
  }
  return (
    <Paper component="section" withBorder p="md">
      <Title order={3}>Recommended setup</Title>
      <Text size="sm" c="dimmed">
        {intent.functional} · Quantum ESPRESSO
      </Text>
      <SimpleGrid component="dl" cols={{ base: 2, sm: 4 }} mb={0}>
        <div>
          <Text component="dt" size="sm" c="dimmed">
            K-grid
          </Text>
          <Text component="dd" m={0}>
            {result.records.k_points?.grid.join(" × ") ?? "Not returned"}
          </Text>
        </div>
        <div>
          <Text component="dt" size="sm" c="dimmed">
            Wavefunction
          </Text>
          <Text component="dd" m={0}>
            {wavefunction === null
              ? "Table default"
              : `${String(wavefunction)} Ry`}
          </Text>
        </div>
        <div>
          <Text component="dt" size="sm" c="dimmed">
            Charge density
          </Text>
          <Text component="dd" m={0}>
            {density === null ? "Table default" : `${String(density)} Ry`}
          </Text>
        </div>
        <div>
          <Text component="dt" size="sm" c="dimmed">
            Spin
          </Text>
          <Text component="dd" m={0}>
            {spin}
          </Text>
        </div>
      </SimpleGrid>
    </Paper>
  );
}

function Warnings({ result }: { readonly result: ComputationResult }) {
  const selection = result.records.selection;
  const warnings = [
    ...new Set([
      ...result.warnings,
      ...(selection?.warnings ?? []),
      ...(selection?.pseudopotentials.flatMap((item) => item.warnings) ?? []),
    ]),
  ];
  if (warnings.length === 0) return null;
  return (
    <Alert
      title="Scientific warnings"
      role="status"
      aria-live="polite"
      aria-atomic="true"
    >
      <Stack component="ul" gap="xs" m={0} pl="md">
        {warnings.map((warning) => (
          <li key={warning}>{warning}</li>
        ))}
      </Stack>
    </Alert>
  );
}

function maximum(values: readonly (number | null)[]): number | null {
  const present = values.filter((value): value is number => value !== null);
  return present.length === 0 ? null : Math.max(...present);
}
