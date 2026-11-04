import { Group, Paper, Text, Title } from "@mantine/core";

import { MagneticOrderingsPanel } from "../advisors/MagneticOrderingsPanel";

/** Auto-shown by `Workbench` only once the magnetic decision resolves
 * spin-polarized -- see `App.tsx`'s `showMagneticOrderings` -- rather
 * than always present like the other four columns, since exploring
 * alternative magnetic orderings is meaningless for a spin-unpolarized
 * run. */
export function MagneticOrderingsCard({ kicker }: { readonly kicker: string }) {
  return (
    <Paper
      component="section"
      id="magnetic-orderings-panel"
      aria-label="Magnetic orderings"
      withBorder
      p="md"
      className="workbench-card card-magnetic-orderings"
    >
      <Group component="header" className="card-header" mb="md" wrap="nowrap">
        <Text className="card-kicker">{kicker}</Text>
        <Title order={2}>Magnetic Orderings</Title>
      </Group>
      {/* eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex -- axe's scrollable-region-focusable rule requires this overflow-y:auto container itself to be keyboard-reachable, not just its children. */}
      <div className="card-body" tabIndex={0}>
        <MagneticOrderingsPanel />
      </div>
    </Paper>
  );
}
