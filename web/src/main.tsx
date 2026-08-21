import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import { HttpWorkbenchClient } from "./api/workbenchClient";
import "./styles.css";
import { WorkspaceProvider } from "./workspace/WorkspaceProvider";
import { createWorkspace } from "./workspace/workspace";

const workspace = createWorkspace(new HttpWorkbenchClient());
const root = document.querySelector("#root");

if (root === null) {
  throw new Error("Goldilocks Workbench root element is missing");
}

createRoot(root).render(
  <StrictMode>
    <WorkspaceProvider workspace={workspace}>
      <App />
    </WorkspaceProvider>
  </StrictMode>,
);
