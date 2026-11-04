import { Alert, Box, Button, Group, Text } from "@mantine/core";
import { RotateCw } from "lucide-react";

import { type CoreFailure, findingsOf } from "../api/coreClient";
import { FindingList } from "./FindingNote";

/** A failure with Retry and, but for a capabilities failure, Dismiss. A
 * refused `/run` lists its findings, each with a button per remedy, in
 * place of the message that joins them (#151). */
export function FailureBanner({
  failure,
  dismissAvailable,
  onRetry,
  onDismiss,
}: {
  readonly failure: CoreFailure;
  readonly dismissAvailable: boolean;
  readonly onRetry: () => void;
  readonly onDismiss: () => void;
}) {
  const findings = findingsOf(failure);
  return (
    <Alert
      className="failure-banner"
      color="red"
      title={FAILURE_TITLES[failure.kind] ?? "Calculation failed"}
      withCloseButton={dismissAvailable}
      closeButtonLabel="Dismiss error"
      styles={{ closeButton: { width: 44, height: 44 } }}
      onClose={onDismiss}
      role="alert"
    >
      <Group justify="space-between">
        {findings.length === 0 ? (
          <Text flex={1}>{failure.message}</Text>
        ) : (
          <Box flex={1}>
            <FindingList findings={findings} />
          </Box>
        )}
        <Button
          color="red"
          variant="light"
          onClick={onRetry}
          leftSection={<RotateCw aria-hidden="true" size={15} />}
        >
          Retry
        </Button>
      </Group>
    </Alert>
  );
}

// Intended to stay in sync with every ExpectedFailure.kind reachable
// through the v2 HTTP transport (grep `kind = "..."` across
// src/goldilocks_core/), plus the client-only kinds coreClient.ts
// synthesizes itself -- though this is a manually maintained list, not
// a generated one, so it can drift. An unrecognized kind still degrades
// to the generic fallback title below rather than failing loudly --
// acceptable per #12's own scope note, since `failure.message` is
// always shown regardless.
const FAILURE_TITLES: Readonly<Record<string, string>> = {
  invalid_request: "Check the request",
  invalid_setting: "Check your overrides",
  advice_incomplete: "Recommendation incomplete",
  invalid_hpc_profile: "Check the HPC profile",
  invalid_structure: "Check the structure",
  assets_unavailable: "Runtime assets unavailable",
  asset_not_installed: "Runtime assets unavailable",
  asset_corrupt: "Runtime assets unavailable",
  pseudo_import_error: "Pseudopotential import failed",
  generation_error: "Could not generate input files",
  submission_error: "Could not generate the submission script",
  network_error: "Cannot reach Core",
  invalid_response: "Unexpected server response",
  http_error: "Request failed",
  incompatible_vocabulary: "Frontend/backend version mismatch",
};
