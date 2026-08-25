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
      className="visually-hidden"
      role="status"
      aria-label="Workbench status"
      aria-live="polite"
      aria-atomic="true"
    >
      {operationMessage(operation, hasFailure)}
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
