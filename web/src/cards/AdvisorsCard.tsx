import { Group, Paper, Text, Title } from "@mantine/core";

import { CalculationForm } from "../controls/CalculationForm";
import { ClearedOverridesNotice } from "../controls/ClearedOverridesNotice";
import { useWorkspaceSnapshot } from "../workspace/useWorkspace";

export function AdvisorsCard({ kicker }: { readonly kicker: string }) {
  const snapshot = useWorkspaceSnapshot();
  return (
    <Paper
      component="section"
      id="advisors-panel"
      aria-label="Goldilocks advisors"
      withBorder
      p="md"
      className="workbench-card card-advisors"
    >
      <Group component="header" className="card-header" mb="md" wrap="nowrap">
        <Text className="card-kicker">{kicker}</Text>
        <Title order={2}>Advisors</Title>
      </Group>
      {/* Above the scrolling body, so it is in view whatever the body's
       * scroll position when another structure opens. */}
      <ClearedOverridesNotice />
      {/* eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex -- axe's scrollable-region-focusable rule requires this overflow-y:auto container itself to be keyboard-reachable, not just its children. */}
      <div className="card-body" tabIndex={0}>
        {snapshot.capabilities === null ? (
          <Text c="dimmed">Load a structure to configure a calculation.</Text>
        ) : (
          <CalculationForm />
        )}
      </div>
    </Paper>
  );
}
