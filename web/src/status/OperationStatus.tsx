import { VisuallyHidden } from "@mantine/core";
import type { WorkspaceOperation } from "../workspace/workspace";

/** The request in flight, or else whether something waits for the user
 * (`pipelineStatus.needsAttention`). */
export function OperationStatus({
  operation,
  needsAttention,
}: {
  readonly operation: WorkspaceOperation | null;
  readonly needsAttention: boolean;
}) {
  return (
    <VisuallyHidden
      role="status"
      aria-label="Workbench status"
      aria-live="polite"
      aria-atomic="true"
    >
      {operationMessage(operation, needsAttention)}
    </VisuallyHidden>
  );
}

const OPERATION_MESSAGES: Readonly<Record<WorkspaceOperation, string>> = {
  capabilities: "Loading capabilities",
  inspect: "Inspecting structure",
  explain: "Computing recommendation",
  preview: "Generating input files",
};

function operationMessage(
  operation: WorkspaceOperation | null,
  needsAttention: boolean,
): string {
  if (operation !== null) return OPERATION_MESSAGES[operation];
  return needsAttention ? "Needs attention" : "Ready";
}
