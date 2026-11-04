import { Group, Loader, Paper, Stack, Text, Title } from "@mantine/core";
import { Atom } from "lucide-react";

import { CalculationContextControls } from "../controls/CalculationForm";
import { StructureSourceControls } from "../controls/StructureSourceControls";
import { StructureViewport } from "../viewer/StructureViewport";
import { useWorkspace, useWorkspaceSnapshot } from "../workspace/useWorkspace";

export function StructureCard({ kicker }: { readonly kicker: string }) {
  const workspace = useWorkspace();
  const snapshot = useWorkspaceSnapshot();

  return (
    <Paper
      component="section"
      id="structure-panel"
      aria-label="Structure workspace"
      withBorder
      p="md"
      className="workbench-card card-structure"
    >
      <Group component="header" className="card-header" mb="md" wrap="nowrap">
        <Text className="card-kicker">{kicker}</Text>
        <Title order={2}>Structure Setup</Title>
      </Group>
      {/* eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex -- axe's scrollable-region-focusable rule requires this overflow-y:auto container itself to be keyboard-reachable, not just its children. */}
      <div className="card-body" tabIndex={0}>
        <StructureSourceControls
          source={snapshot.structureInput}
          inspection={snapshot.inspection}
          inspecting={snapshot.operation === "inspect"}
          onOpen={(input) => workspace.dispatch({ type: "source.open", input })}
        />
        <CalculationContextControls />
        <div className="structure-stage">
          {snapshot.inspection === null ? (
            <EmptyStage
              loading={
                snapshot.capabilities === null ||
                snapshot.operation === "inspect"
              }
              label={
                snapshot.capabilities === null ? "Loading Workbench" : undefined
              }
            />
          ) : (
            <StructureViewport inspection={snapshot.inspection} />
          )}
        </div>
      </div>
    </Paper>
  );
}

function EmptyStage({
  loading,
  label = loading ? "Reading structure" : "No structure selected",
}: {
  readonly loading: boolean;
  readonly label?: string | undefined;
}) {
  return (
    <Stack
      align="center"
      justify="center"
      h="100%"
      p="xl"
      gap="xl"
      role={loading ? "status" : undefined}
    >
      {loading ? (
        <Loader size="xl" aria-hidden="true" />
      ) : (
        <Atom size={96} strokeWidth={1} aria-hidden="true" />
      )}
      <Title order={3} ta="center">
        {label}
      </Title>
    </Stack>
  );
}
