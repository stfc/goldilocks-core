import { useState } from "react";
import { Alert, List, Text } from "@mantine/core";

import { useWorkspaceSnapshot } from "../workspace/useWorkspace";
import { overrideLabel } from "./overrideFieldMeta";

/** Names the overrides that opening the current structure set back to
 * automatic (`WorkspaceSnapshot.clearedOverrides`, #188), by the labels of
 * their controls. Dismissing it hides that list only: the next structure
 * that clears overrides stores a new list, which shows again. */
export function ClearedOverridesNotice() {
  const { capabilities, clearedOverrides } = useWorkspaceSnapshot();
  const [dismissed, setDismissed] = useState<readonly string[] | null>(null);
  if (
    capabilities === null ||
    clearedOverrides.length === 0 ||
    clearedOverrides === dismissed
  ) {
    return null;
  }
  return (
    <Alert
      role="status"
      title="Structure-specific overrides reset"
      withCloseButton
      closeButtonLabel="Dismiss notice"
      styles={{ closeButton: { width: 44, height: 44 } }}
      onClose={() => {
        setDismissed(clearedOverrides);
      }}
      mb="md"
    >
      <Text size="sm">Opening this structure set these back to automatic:</Text>
      <List size="sm">
        {clearedOverrides.map((key) => (
          <List.Item key={key}>
            {overrideLabel(key, capabilities.settings)}
          </List.Item>
        ))}
      </List>
    </Alert>
  );
}
