import type { ReactNode } from "react";

import { WorkspaceContext } from "./workspaceContext";
import type { Workspace } from "./workspace";

export function WorkspaceProvider({
  workspace,
  children,
}: {
  readonly workspace: Workspace;
  readonly children: ReactNode;
}) {
  return (
    <WorkspaceContext.Provider value={workspace}>
      {children}
    </WorkspaceContext.Provider>
  );
}
