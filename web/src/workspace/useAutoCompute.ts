import { useEffect } from "react";

import { explainDue, previewDue } from "./pipelineStatus";
import type { Workspace, WorkspaceSnapshot } from "./workspace";

const AUTO_COMPUTE_DEBOUNCE_MS = 400;
const AUTO_PREVIEW_DEBOUNCE_MS = 150;

/** There is no manual "generate"/"update recommendation" control in the
 * UI: the open structure's current draft is sent to `/explain`
 * automatically (debounced) on load and after every settings change, and
 * once its recommendation arrives with no blocking reason, its archive is
 * fetched from `/run` as the generated-inputs preview. The "Download"
 * button only saves that archive. Each request is sent only while the
 * current draft has no outcome for it (`explainDue`, `previewDue`): a
 * failure is that draft's outcome, so a failing request is not sent again
 * until the draft or the structure changes or the user presses Retry
 * (#150). */
export function useAutoCompute(
  workspace: Workspace,
  snapshot: WorkspaceSnapshot,
): void {
  const { revision } = snapshot;
  const sendExplain = explainDue(snapshot);
  const sendPreview = previewDue(snapshot);

  // `revision` restarts the debounce on every edit.
  useEffect(() => {
    if (!sendExplain) return;
    const timer = setTimeout(() => {
      void workspace.dispatch({ type: "review.compute" });
    }, AUTO_COMPUTE_DEBOUNCE_MS);
    return () => {
      clearTimeout(timer);
    };
  }, [workspace, sendExplain, revision]);

  useEffect(() => {
    if (!sendPreview) return;
    const timer = setTimeout(() => {
      void workspace.dispatch({ type: "review.refreshArchive" });
    }, AUTO_PREVIEW_DEBOUNCE_MS);
    return () => {
      clearTimeout(timer);
    };
  }, [workspace, sendPreview, revision]);
}
