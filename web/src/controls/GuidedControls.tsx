import type { ReactNode } from "react";
import { ActionIcon, Group } from "@mantine/core";
import { Moon, Sun } from "lucide-react";

import type { Theme } from "../theme";
import { useWorkspace, useWorkspaceSnapshot } from "../workspace/useWorkspace";
import { CalculationForm } from "./CalculationForm";
import { StructureSourceControls } from "./StructureSourceControls";
import "./GuidedControls.css";

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
    <section
      id="calculation-panel"
      className="control-rail"
      aria-label="Calculation setup"
    >
      <section className="rail-section rail-section--source">
        <SectionHeading
          number="01"
          title="Structure"
          action={
            <ActionIcon
              className="theme-toggle"
              variant="default"
              size="var(--target-size)"
              aria-label={
                theme === "light"
                  ? "Switch to dark mode"
                  : "Switch to light mode"
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
          }
        />
        <StructureSourceControls
          source={snapshot.source}
          inspection={snapshot.inspection}
          inspecting={snapshot.operation === "inspect"}
          onOpen={(source) => {
            onShowStructure();
            return workspace.dispatch({ type: "source.open", source });
          }}
        />
      </section>

      <section className="rail-section rail-section--calculation">
        <SectionHeading number="02" title="Calculation" />
        <CalculationForm onShowRecommendation={onShowRecommendation} />
      </section>
    </section>
  );
}

function SectionHeading({
  number,
  title,
  action,
}: {
  readonly number: string;
  readonly title: string;
  readonly action?: ReactNode;
}) {
  return (
    <Group
      component="header"
      justify="space-between"
      gap="var(--space-3)"
      mb="var(--space-5)"
      wrap="nowrap"
      className="section-heading"
    >
      <Group gap="var(--space-3)" wrap="nowrap">
        <span>{number}</span>
        <h2>{title}</h2>
      </Group>
      {action}
    </Group>
  );
}
