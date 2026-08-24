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
    <div className="failure-banner" role="alert">
      <div>
        <strong>{failureTitle(failure.kind)}</strong>
        <span>{failure.message}</span>
      </div>
      <div className="failure-banner__actions">
        {retryAvailable ? (
          <button type="button" onClick={onRetry}>
            <RotateCw aria-hidden="true" size={15} />
            Retry
          </button>
        ) : null}
        {dismissAvailable ? (
          <button type="button" aria-label="Dismiss error" onClick={onDismiss}>
            <X aria-hidden="true" size={17} />
          </button>
        ) : null}
      </div>
    </div>
  );
}

function failureTitle(kind: string): string {
  switch (kind) {
    case "invalid_request":
      return "Check the request";
    case "assets_unavailable":
    case "asset_not_installed":
    case "asset_corrupt":
      return "Runtime assets unavailable";
    case "server_busy":
      return "Workbench is busy";
    case "invalid_structure":
      return "Check the structure";
    case "pseudo_table_mismatch":
      return "Pseudopotential set mismatch";
    case "network_error":
      return "Cannot reach Core";
    case "invalid_response":
      return "Unexpected server response";
    default:
      return "Calculation failed";
  }
}
