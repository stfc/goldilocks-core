import { Alert, Stack, Text } from "@mantine/core";

import type { AdvisorWarning, RecordWarning } from "../api/coreClient";
import { WARNING_LEVEL_COLORS } from "./warnings";

const WARNING_LEVEL_TITLES: Readonly<Record<AdvisorWarning["level"], string>> =
  {
    error: "Errors",
    warning: "Warnings",
    info: "Notices",
  };

/** Neither the code nor the record and code identify a warning: two
 * records raise the same code (a dos task's `parallelisation` and
 * `nscf_parallelisation`), and one record raises a code once per element
 * (`hubbard.u_value_missing`). The message tells those apart. */
function warningKey(warning: AdvisorWarning | RecordWarning): string {
  const record = "record" in warning ? warning.record : null;
  return JSON.stringify([record, warning.code, warning.message]);
}

export function WarningsPanel({
  warnings,
}: {
  readonly warnings: readonly (AdvisorWarning | RecordWarning)[];
}) {
  if (warnings.length === 0) return null;
  // Mantine's Alert already pairs its own background/text colors
  // accessibly per `color` -- one alert per severity level conveys the
  // level through that pairing instead of a per-item colored badge
  // nested inside an already-tinted alert, which axe flags for
  // insufficient contrast at small text sizes regardless of which
  // Mantine color/variant is chosen for the inner badge.
  return (
    <Stack gap="sm">
      {(["error", "warning", "info"] as const).map((level) => {
        const atLevel = warnings.filter((warning) => warning.level === level);
        if (atLevel.length === 0) return null;
        return (
          <Alert
            key={level}
            color={WARNING_LEVEL_COLORS[level]}
            variant="filled"
            autoContrast
            title={WARNING_LEVEL_TITLES[level]}
            role="status"
            aria-live="polite"
            aria-atomic="true"
          >
            <Stack component="ul" gap="xs" m={0} pl="md">
              {atLevel.map((warning) => (
                <Text component="li" key={warningKey(warning)} size="sm">
                  {warning.message}
                </Text>
              ))}
            </Stack>
          </Alert>
        );
      })}
    </Stack>
  );
}
