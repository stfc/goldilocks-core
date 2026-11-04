import type { AdvisorWarning } from "../api/coreClient";

export function isAdvisorWarning(value: unknown): value is AdvisorWarning {
  return (
    typeof value === "object" &&
    value !== null &&
    "code" in value &&
    "level" in value &&
    "category" in value &&
    "message" in value &&
    typeof value.message === "string"
  );
}

// Explicit `.8` shade for blue: Mantine's default filled shade (6) is
// #1c7ed6, whose white-on-filled contrast is only 4.19:1 (needs 4.5) --
// confirmed with axe against a live render. `autoContrast` (see
// WarningsPanel.tsx) correctly picks white vs. black text per background
// luminance, but doesn't itself darken a shade that's merely borderline.
export const WARNING_LEVEL_COLORS: Readonly<
  Record<AdvisorWarning["level"], string>
> = {
  info: "blue.8",
  warning: "yellow",
  error: "red",
};
