import { ActionIcon, Group, Paper, Stack, Text, Title } from "@mantine/core";
import { Moon, Sun } from "lucide-react";

import type { Theme } from "../theme";
import { useWorkspace, useWorkspaceSnapshot } from "../workspace/useWorkspace";
import { CalculationForm } from "./CalculationForm";
import { StructureSourceControls } from "./StructureSourceControls";

export function GuidedControls({
  theme,
  onToggleTheme,
  onShowStructure,
  onShowRecommendation,
}: {
  readonly theme: Theme;
  readonly onToggleTheme: () => void;
  readonly onShowStructure: () => void;
  readonly onShowRecommendation: () => void;
}) {
  const workspace = useWorkspace();
  const snapshot = useWorkspaceSnapshot();
  return (
    <Stack
      component="section"
      id="calculation-panel"
      aria-label="Calculation setup"
      gap={0}
      miw={0}
    >
      <Paper component="section" withBorder p="md">
        <Group component="header" justify="space-between" mb="md" wrap="nowrap">
          <Group wrap="nowrap">
            <Text c="dimmed">01</Text>
            <Title order={2}>Structure</Title>
          </Group>
          <ActionIcon
            variant="default"
            aria-label={
              theme === "light" ? "Switch to dark mode" : "Switch to light mode"
            }
            title={theme === "light" ? "Dark mode" : "Light mode"}
            onClick={onToggleTheme}
          >
            {theme === "light" ? (
              <Sun aria-hidden="true" size={17} />
            ) : (
              <Moon aria-hidden="true" size={17} />
            )}
          </ActionIcon>
        </Group>
        <StructureSourceControls
          source={snapshot.source}
          inspection={snapshot.inspection}
          inspecting={snapshot.operation === "inspect"}
          onOpen={(source) => {
            onShowStructure();
            return workspace.dispatch({ type: "source.open", source });
          }}
        />
      </Paper>

      <Paper component="section" withBorder p="md">
        <Group component="header" mb="md" wrap="nowrap">
          <Text c="dimmed">02</Text>
          <Title order={2}>Calculation</Title>
        </Group>
        <CalculationForm onShowRecommendation={onShowRecommendation} />
      </Paper>
    </Stack>
  );
}
