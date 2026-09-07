import { Box, Button, Flex, Group, Stack, Text } from "@mantine/core";
import { ArrowLeft, Download, LoaderCircle } from "lucide-react";

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
    <section
      id="recommendation-panel"
      className="review-panel"
      aria-label="Recommendation results"
      aria-busy={snapshot.operation === "compute"}
    >
      <Group
        component="header"
        className="review-heading"
        justify="space-between"
        wrap="nowrap"
        gap={0}
      >
        <Group gap={12} wrap="nowrap">
          <span>03</span>
          <h2>Recommendation</h2>
        </Group>
        <Button
          className="panel-navigation"
          leftSection={<ArrowLeft aria-hidden="true" size={15} />}
          aria-label="Back to structure"
          onClick={onShowStructure}
        >
          Structure
        </Button>
      </Group>

      {result === null && (
        <Stack
          className="review-empty"
          align="center"
          justify="center"
          gap={0}
          role={snapshot.operation === "compute" ? "status" : undefined}
        >
          {snapshot.operation === "compute" ? (
            <LoaderCircle
              className="spinning-icon"
              aria-hidden="true"
              size={18}
              style={{ marginBottom: 16, color: "var(--color-accent-bright)" }}
            />
          ) : (
            <div className="review-empty__diagram" aria-hidden="true">
              <span />
              <span />
              <span />
            </div>
          )}
          <Text component="strong" fz="var(--text-lg)" fw={550} lh="inherit">
            {snapshot.operation === "compute"
              ? "Computing recommendation"
              : "No recommendation"}
          </Text>
        </Stack>
      )}
      {result !== null && (
        <>
          {snapshot.outOfDate ? (
            <Box
              className="stale-banner"
              role="status"
              aria-label="Recommendation notice"
              aria-live="polite"
              aria-atomic="true"
              fz="var(--text-sm)"
            >
              Your settings changed. Update the recommendation before
              downloading.
            </Box>
          ) : null}
          <Flex className="download-bar" justify="space-between" gap={16}>
            <Button
              classNames={{
                root: "download-action",
                inner: "download-action__inner",
              }}
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
              <p
                className="archive-receipt"
                role="status"
                aria-label="Archive status"
                aria-live="polite"
              >
                {snapshot.lastDownload.filename} is ready
              </p>
            )}
          </Flex>
          <GeneratedInputReview result={result} />
          <RecommendationSummary result={result} />
          <PseudopotentialReview result={result} />
          <RecordReview result={result} />
          <Warnings result={result} />
        </>
      )}
    </section>
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
    <section className="review-section recommendation-summary">
      <Group component="header" gap={12} wrap="nowrap" mb={16}>
        <span className="review-section__index">B</span>
        <div>
          <h3>Recommended setup</h3>
          <p>{intent.functional} · Quantum ESPRESSO</p>
        </div>
      </Group>
      <dl className="recommendation-metrics">
        <div>
          <dt>K-grid</dt>
          <dd>{result.records.k_points?.grid.join(" × ") ?? "Not returned"}</dd>
        </div>
        <div>
          <dt>Wavefunction</dt>
          <dd>
            {wavefunction === null
              ? "Table default"
              : `${String(wavefunction)} Ry`}
          </dd>
        </div>
        <div>
          <dt>Charge density</dt>
          <dd>
            {density === null ? "Table default" : `${String(density)} Ry`}
          </dd>
        </div>
        <div>
          <dt>Spin</dt>
          <dd>{spin}</dd>
        </div>
      </dl>
    </section>
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
    <Box
      className="warning-list"
      role="status"
      aria-label="Scientific warnings"
      aria-live="polite"
      aria-atomic="true"
    >
      <h3>Warnings</h3>
      <Stack component="ul" gap={8} mt={12} mb={0} pl={20}>
        {warnings.map((warning) => (
          <li key={warning}>{warning}</li>
        ))}
      </Stack>
    </Box>
  );
}

function maximum(values: readonly (number | null)[]): number | null {
  const present = values.filter((value): value is number => value !== null);
  return present.length === 0 ? null : Math.max(...present);
}
