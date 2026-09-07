import { Alert, Button, Group, Text } from "@mantine/core";
import { RotateCw } from "lucide-react";

import type { CoreFailure } from "../api/coreClient";

export function FailureBanner({
  failure,
  retryAvailable,
  dismissAvailable,
  onRetry,
  onDismiss,
}: {
  readonly failure: CoreFailure;
  readonly retryAvailable: boolean;
  readonly dismissAvailable: boolean;
  readonly onRetry: () => void;
  readonly onDismiss: () => void;
}) {
  return (
    <Alert
      color="red"
      title={FAILURE_TITLES[failure.kind] ?? "Calculation failed"}
      withCloseButton={dismissAvailable}
      closeButtonLabel="Dismiss error"
      styles={{ closeButton: { width: 44, height: 44 } }}
      onClose={onDismiss}
      role="alert"
    >
      <Group justify="space-between">
        <Text flex={1}>{failure.message}</Text>
        {retryAvailable ? (
          <Button
            color="red"
            variant="light"
            onClick={onRetry}
            leftSection={<RotateCw aria-hidden="true" size={15} />}
          >
            Retry
          </Button>
        ) : null}
      </Group>
    </Alert>
  );
}

const FAILURE_TITLES: Readonly<Record<string, string>> = {
  invalid_request: "Check the request",
  assets_unavailable: "Runtime assets unavailable",
  asset_not_installed: "Runtime assets unavailable",
  asset_corrupt: "Runtime assets unavailable",
  invalid_structure: "Check the structure",
  pseudo_table_mismatch: "Pseudopotential set mismatch",
  network_error: "Cannot reach Core",
  invalid_response: "Unexpected server response",
};
