import { useEffect } from "react";
import type { CSSProperties } from "react";
import {
  MantineProvider,
  VisuallyHidden,
  useComputedColorScheme,
  useMantineColorScheme,
} from "@mantine/core";

import type { ResolvedField } from "./api/coreClient";
import { AdvisorsCard } from "./cards/AdvisorsCard";
import { AnalysisCard } from "./cards/AnalysisCard";
import { BundleCard } from "./cards/BundleCard";
import { MagneticOrderingsCard } from "./cards/MagneticOrderingsCard";
import { StructureCard } from "./cards/StructureCard";
import { AppHeader } from "./layout/AppHeader";
import { FailureBanner } from "./status/FailureBanner";
import { OperationStatus } from "./status/OperationStatus";
import { colorSchemeManager, workbenchTheme } from "./theme";
import { bannerFailure, needsAttention } from "./workspace/pipelineStatus";
import { useAutoCompute } from "./workspace/useAutoCompute";
import { useWorkspace, useWorkspaceSnapshot } from "./workspace/useWorkspace";
import "./App.css";

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

// Header-less: everything `Workbench` renders except `AppHeader` -- the
// piece goldilocks-agent embeds directly into its own app shell (which has
// its own header/navigation already), re-exported via `index.ts`'s library
// build for that purpose. Kept in sync with `Workbench` below by
// construction (one calls the other), not by duplicating this JSX a
// second time. It fills its container's height (App.css,
// `.workbench-content`).
export function WorkbenchContent() {
  const workspace = useWorkspace();
  const snapshot = useWorkspaceSnapshot();
  useAutoCompute(workspace, snapshot);

  // Magnetic-ordering exploration is only meaningful for a spin-polarized
  // run -- rather than a fifth column that's always present but usually
  // empty, it pops in between Advisors and Bundle exactly when the
  // magnetic decision resolves spin-polarized, and the grid itself grows
  // from four to five columns to match. It follows the decision, not the
  // is_magnetic classifier, so a spin_polarized or magnetic_ordering
  // setting that overrides a non-magnetic classification shows it too
  // (#145).
  const showMagneticOrderings = spinPolarized(
    snapshot.reviewed?.records.magnetic,
  );
  // Structure, Analysis and Advisors sit on the narrow column floor,
  // Magnetic Orderings and Bundle on the wide one; App.css caps the grid's
  // width no lower than these floors add up to (#190).
  const wideColumns = showMagneticOrderings ? 2 : 1;
  const columns = 3 + wideColumns;
  // Every failure offers Retry, a deterministic 4xx too: it sends the failed
  // request once more. Dismiss only hides the banner; the failure stays the
  // outcome of its draft, so nothing is sent again on its own (#150).
  const banner = bannerFailure(snapshot);

  return (
    <div className="workbench-content">
      <OperationStatus
        operation={snapshot.operation}
        needsAttention={needsAttention(snapshot)}
      />

      {banner === null ? null : (
        <FailureBanner
          failure={banner.failure}
          dismissAvailable={banner.operation !== "capabilities"}
          onRetry={() => {
            void workspace.dispatch({
              type: "failure.retry",
              operation: banner.operation,
            });
          }}
          onDismiss={() => {
            void workspace.dispatch({
              type: "failure.dismiss",
              operation: banner.operation,
            });
          }}
        />
      )}

      <main
        className="workbench-grid"
        aria-labelledby="workbench-title"
        style={
          {
            "--workbench-columns": columns,
            "--workbench-wide-columns": wideColumns,
          } as CSSProperties
        }
      >
        <VisuallyHidden>
          <h1 id="workbench-title">Goldilocks SCF setup</h1>
        </VisuallyHidden>
        <StructureCard kicker="01" />
        <AnalysisCard kicker="02" />
        <AdvisorsCard kicker="03" />
        {showMagneticOrderings ? <MagneticOrderingsCard kicker="04" /> : null}
        <BundleCard kicker={showMagneticOrderings ? "05" : "04"} />
      </main>
    </div>
  );
}

/** Whether a magnetic record resolved to a spin-polarized run. */
function spinPolarized(record: ResolvedField | undefined): boolean {
  if (record?.status !== "resolved") return false;
  const value = record.value;
  if (typeof value !== "object" || value === null) return false;
  return (value as Readonly<Record<string, unknown>>).spin_polarized === true;
}

function Workbench() {
  const theme = useComputedColorScheme("light");
  const { toggleColorScheme: toggleTheme } = useMantineColorScheme();
  useEffect(() => {
    document
      .querySelector<HTMLMetaElement>('meta[name="theme-color"]')
      ?.setAttribute("content", theme === "light" ? "#ffffff" : "#242424");
  }, [theme]);

  return (
    <div className="app-layout">
      <AppHeader theme={theme} onToggleTheme={toggleTheme} />
      <WorkbenchContent />
    </div>
  );
}
