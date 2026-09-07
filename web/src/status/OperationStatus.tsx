import { VisuallyHidden } from "@mantine/core";
import type { WorkspaceOperation } from "../workspace/workspace";

export function OperationStatus({
  operation,
  hasFailure,
}: {
  readonly operation: WorkspaceOperation | null;
  readonly hasFailure: boolean;
}) {
  return (
    <VisuallyHidden
      role="status"
      aria-label="Workbench status"
      aria-live="polite"
      aria-atomic="true"
    >
      {operationMessage(operation, hasFailure)}
    </VisuallyHidden>
  );
}

const OPERATION_MESSAGES: Readonly<Record<WorkspaceOperation, string>> = {
  capabilities: "Loading capabilities",
  inspect: "Inspecting structure",
  compute: "Computing recommendation",
};

function operationMessage(
  operation: WorkspaceOperation | null,
  hasFailure: boolean,
): string {
  if (hasFailure) return "Needs attention";
  return operation === null ? "Ready" : OPERATION_MESSAGES[operation];
}
