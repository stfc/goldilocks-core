import { createContext } from "react";

import type { Workspace } from "./workspace";

export const WorkspaceContext = createContext<Workspace | null>(null);
