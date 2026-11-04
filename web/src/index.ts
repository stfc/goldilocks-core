// Library-mode entry point (see ../vite.lib.config.ts) -- the surface
// goldilocks-agent (or any other embedder) imports from the published
// `goldilocks-workbench` package. Kept deliberately narrow: only what an
// embedder actually needs to render the Workbench inside its own app shell
// and drive it from outside (WorkspaceProvider/createWorkspace/useWorkspace)
// or talk to core directly (HttpCoreClient).
//
// Mantine's own base/reset stylesheet (component recipes like
// VisuallyHidden's `position: absolute`, not just per-component CSS
// modules already pulled in automatically when those components are
// imported) is only ever imported once, globally, in main.tsx for the
// standalone app -- an embedder has no equivalent entry point to put it
// in, so it has to be re-exported from here instead. Without it,
// VisuallyHidden's hidden <h1> falls back to `position: static` and
// becomes a real 5th grid item inside .workbench-grid, pushing the
// Bundle card into a broken second row -- a real bug, verified live
// (2026-09-24) via computed-style inspection before this fix, not
// assumed from reading Mantine's docs.
import "@mantine/core/styles.layer.css";

export { MantineProvider } from "@mantine/core";
export { App } from "./App";
// WorkbenchContent fills the height of its container: the failure banner,
// when shown, above the card grid, which takes the rest while each card
// scrolls its own body. Give it a container of definite height, such as the
// space below the embedder's own header in a 100dvh flex column; in an
// auto-height container the cards grow with their content instead. At
// widths up to 47.5rem the cards stack at their own height, so the
// container (or the page) scrolls.
export { WorkbenchContent } from "./App";
export { colorSchemeManager, workbenchTheme } from "./theme";
export type { Theme } from "./theme";
export { WorkspaceProvider } from "./workspace/WorkspaceProvider";
export { createWorkspace, currentOrderings } from "./workspace/workspace";
export type {
  CalculationDraft,
  InspectFailure,
  MagneticOrderingsListing,
  PipelineKey,
  PipelineOutcome,
  Workspace,
  WorkspaceAction,
  WorkspaceOperation,
  WorkspaceSnapshot,
} from "./workspace/workspace";
// The snapshot keeps the latest /explain and preview outcome with the
// structure and revision it belongs to; these read the current draft's.
// `currentFindings` are the current draft's blocking findings, from its
// /explain verdict or its refused preview /run, each with its remedies.
export {
  bannerFailure,
  currentArchive,
  currentExplain,
  currentFindings,
  currentPreview,
} from "./workspace/pipelineStatus";
export type { WorkspaceFailure } from "./workspace/pipelineStatus";
export { useWorkspace, useWorkspaceSnapshot } from "./workspace/useWorkspace";
export { HttpCoreClient, findingsOf } from "./api/coreClient";
export type {
  BlockingFinding,
  CoreClient,
  StructureInput,
} from "./api/coreClient";
// Code/Task/HPC-profile pickers, self-contained (reads useWorkspace/
// useWorkspaceSnapshot itself, no props) -- re-exported so an embedder can
// build a custom Structure Setup surface (e.g. swapping out
// StructureSourceControls/StructureViewport for its own upload UI) while
// still reusing the real calculation-context controls verbatim, not a
// reimplementation of them.
export { CalculationContextControls } from "./controls/CalculationForm";
