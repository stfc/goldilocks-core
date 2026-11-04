import { Group, Paper, Text, Title } from "@mantine/core";

import { AnalysisSection } from "../analysis/AnalysisSection";
import { useWorkspaceSnapshot } from "../workspace/useWorkspace";

export function AnalysisCard({ kicker }: { readonly kicker: string }) {
  const snapshot = useWorkspaceSnapshot();
  return (
    <Paper
      component="section"
      id="analysis-panel"
      aria-label="Goldilocks analysis"
      withBorder
      p="md"
      className="workbench-card card-analysis"
    >
      <Group component="header" className="card-header" mb="md" wrap="nowrap">
        <Text className="card-kicker">{kicker}</Text>
        <Title order={2}>Analysis</Title>
      </Group>
      {/* eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex -- axe's scrollable-region-focusable rule requires this overflow-y:auto container itself to be keyboard-reachable, not just its children. */}
      <div className="card-body" tabIndex={0}>
        {snapshot.capabilities === null || snapshot.inspection === null ? (
          <Text c="dimmed">Load a structure to see its analysis.</Text>
        ) : (
          <AnalysisSection />
        )}
      </div>
    </Paper>
  );
}
