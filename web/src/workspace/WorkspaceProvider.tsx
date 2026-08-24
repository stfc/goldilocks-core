import { type ReactNode, useEffect } from "react";

import { WorkspaceContext } from "./workspaceContext";
import type { Workspace } from "./workspace";

export function WorkspaceProvider({
  workspace,
  children,
}: {
  readonly workspace: Workspace;
  readonly children: ReactNode;
}) {
  useEffect(() => {
    void workspace.dispatch({ type: "workspace.start" });
  }, [workspace]);

  return (
    <WorkspaceContext.Provider value={workspace}>
      {children}
    </WorkspaceContext.Provider>
  );
}
