import { useLayoutEffect, useEffect, useState } from "react";
import { ArrowRight } from "lucide-react";
import {
  Button,
  MantineProvider,
  useComputedColorScheme,
  useMantineColorScheme,
} from "@mantine/core";

import { GuidedControls } from "./controls/GuidedControls";
import { ReviewPanel } from "./review/ReviewPanel";
import { FailureBanner } from "./status/FailureBanner";
import { OperationStatus } from "./status/OperationStatus";
import { colorSchemeManager, workbenchTheme } from "./theme";
import { StructureViewport } from "./viewer/StructureViewport";
import { WorkspaceLayout } from "./workspace/WorkspaceLayout";
import { useWorkspace, useWorkspaceSnapshot } from "./workspace/useWorkspace";
import "./App.css";

type WorkspaceView = "structure" | "recommendation";

export function App() {
  return (
    <MantineProvider
      theme={workbenchTheme}
      colorSchemeManager={colorSchemeManager}
      defaultColorScheme="light"
    >
      <Workbench />
    </MantineProvider>
  );
}

function Workbench() {
  const workspace = useWorkspace();
  const snapshot = useWorkspaceSnapshot();
  const theme = useComputedColorScheme("light");
  const { toggleColorScheme: toggleTheme } = useMantineColorScheme();
  useEffect(() => {
    document
      .querySelector<HTMLMetaElement>('meta[name="theme-color"]')
      ?.setAttribute("content", theme === "light" ? "#f0eee8" : "#10171b");
  }, [theme]);
  const [workspaceView, setWorkspaceView] =
    useState<WorkspaceView>("structure");

  useLayoutEffect(() => {
    if (workspaceView !== "recommendation") return;
    document.documentElement.scrollTop = 0;
    document.body.scrollTop = 0;
  }, [workspaceView]);

  return (
    <div className="app-shell">
      <OperationStatus
        operation={snapshot.operation}
        hasFailure={snapshot.failure !== null}
      />

      {snapshot.failure === null ? null : (
        <FailureBanner
          failure={snapshot.failure}
          retryAvailable={
            snapshot.failure.retryable ||
            snapshot.failureOperation === "capabilities"
          }
          dismissAvailable={snapshot.capabilities !== null}
          onRetry={() => {
            void workspace.dispatch({ type: "failure.retry" });
          }}
          onDismiss={() => {
            void workspace.dispatch({ type: "failure.dismiss" });
          }}
        />
      )}

      <WorkspaceLayout
        controls={
          snapshot.capabilities === null ? null : (
            <GuidedControls
              theme={theme}
              onToggleTheme={toggleTheme}
              onShowStructure={() => {
                setWorkspaceView("structure");
              }}
              onShowRecommendation={() => {
                setWorkspaceView("recommendation");
              }}
            />
          )
        }
      >
        {workspaceView === "recommendation" ? (
          <ReviewPanel
            onShowStructure={() => {
              setWorkspaceView("structure");
            }}
          />
        ) : (
          <section
            id="structure-panel"
            className="structure-stage"
            aria-label="Structure workspace"
          >
            {snapshot.inspection === null ? (
              <EmptyStage
                loading={
                  snapshot.capabilities === null ||
                  snapshot.operation === "inspect"
                }
                label={
                  snapshot.capabilities === null
                    ? "Loading Workbench"
                    : undefined
                }
              />
            ) : (
              <StructureViewport key={theme} inspection={snapshot.inspection} />
            )}
            {snapshot.reviewed === null ? null : (
              <Button
                className="stage-navigation"
                rightSection={<ArrowRight aria-hidden="true" size={15} />}
                type="button"
                onClick={() => {
                  setWorkspaceView("recommendation");
                }}
              >
                Recommendation
              </Button>
            )}
          </section>
        )}
      </WorkspaceLayout>
    </div>
  );
}

function EmptyStage({
  loading,
  label = loading ? "Reading structure" : "No structure selected",
}: {
  readonly loading: boolean;
  readonly label?: string | undefined;
}) {
  return (
    <div
      className={`empty-stage${loading ? " empty-stage--loading" : ""}`}
      role={loading ? "status" : undefined}
    >
      <div className="empty-stage__orbital" aria-hidden="true">
        <span />
        <span />
        <span />
        <i />
      </div>
      <h2>{label}</h2>
    </div>
  );
}
