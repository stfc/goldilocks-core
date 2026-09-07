import { ActionIcon, Alert, Button } from "@mantine/core";
import { RotateCw, X } from "lucide-react";

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
      className="failure-banner"
      classNames={{
        body: "failure-banner__body",
        message: "failure-banner__message",
      }}
      role="alert"
    >
      <div className="failure-banner__copy">
        <strong>{FAILURE_TITLES[failure.kind] ?? "Calculation failed"}</strong>
        <span className="failure-banner__description">{failure.message}</span>
      </div>
      <div className="failure-banner__actions">
        {retryAvailable ? (
          <Button
            className="failure-banner__action"
            type="button"
            onClick={onRetry}
            leftSection={<RotateCw aria-hidden="true" size={15} />}
          >
            Retry
          </Button>
        ) : null}
        {dismissAvailable ? (
          <ActionIcon
            className="failure-banner__action"
            type="button"
            aria-label="Dismiss error"
            onClick={onDismiss}
          >
            <X aria-hidden="true" size={17} />
          </ActionIcon>
        ) : null}
      </div>
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
