import type { WorkspaceOperation } from "../workspace/workspace";
import "./OperationStatus.css";

export function OperationStatus({
  operation,
}: {
  readonly operation: WorkspaceOperation | null;
}) {
  return (
    <div
      className="header-status"
      role="status"
      aria-label="Workbench status"
      aria-live="polite"
      aria-atomic="true"
    >
      <span className="status-light" aria-hidden="true" />
      <span>{operationMessage(operation)}</span>
      <span className="version-badge" aria-label="Beta">
        β
      </span>
    </div>
  );
}

function operationMessage(operation: WorkspaceOperation | null): string {
  switch (operation) {
    case null:
      return "Ready";
    case "capabilities":
      return "Loading capabilities";
    case "inspect":
      return "Inspecting structure";
    case "compute":
      return "Computing recommendation";
    case "download":
      return "Building archive";
  }
}
