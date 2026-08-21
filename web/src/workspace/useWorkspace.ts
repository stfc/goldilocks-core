import { useCallback, useContext, useSyncExternalStore } from "react";

import type { Workspace, WorkspaceSnapshot } from "./workspace";
import { WorkspaceContext } from "./workspaceContext";

export function useWorkspace(): Workspace {
  const workspace = useContext(WorkspaceContext);
  if (workspace === null) {
    throw new Error("useWorkspace must be rendered inside WorkspaceProvider");
  }
  return workspace;
}

export function useWorkspaceSnapshot(): WorkspaceSnapshot {
  const workspace = useWorkspace();
  const subscribe = useCallback(
    (listener: () => void) => workspace.subscribe(listener),
    [workspace],
  );
  const getSnapshot = useCallback(() => workspace.getSnapshot(), [workspace]);
  return useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
}
