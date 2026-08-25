import type { WorkspaceOperation } from "../workspace/workspace";
import "./OperationStatus.css";

export function OperationStatus({
  operation,
  hasFailure,
}: {
  readonly operation: WorkspaceOperation | null;
  readonly hasFailure: boolean;
}) {
  return (
    <div
      className={`header-status${hasFailure ? " header-status--failure" : ""}`}
    >
      <div
        className="header-status__message"
        role="status"
        aria-label="Workbench status"
        aria-live="polite"
        aria-atomic="true"
      >
        <span className="status-light" aria-hidden="true" />
        <span>{operationMessage(operation, hasFailure)}</span>
      </div>
      <span className="version-badge" aria-label="Beta">
        β
      </span>
    </div>
  );
}

function operationMessage(
  operation: WorkspaceOperation | null,
  hasFailure: boolean,
): string {
  if (hasFailure) return "Needs attention";
  switch (operation) {
    case null:
      return "Ready";
    case "capabilities":
      return "Loading capabilities";
    case "inspect":
      return "Inspecting structure";
    case "compute":
      return "Computing recommendation";
  }
}
