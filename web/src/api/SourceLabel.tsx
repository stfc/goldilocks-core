import { Box } from "@mantine/core";

import type { Source } from "./coreClient";
import { SOURCE_NAMES } from "./sourceNames";

/** Sampled directly from the brand watercolor logo
 * (public/brand/goldilocks-logo.png), left-to-right: red-orange ->
 * purple -> blue -> teal -- the same real-asset-not-invented-palette
 * rule the marketing site's own card colors already follow. Only "ml"
 * gets this treatment: it is the one source name that is itself a
 * product name (Goldilocks-ML), not a generic tier label like the
 * other three. */
const GOLDILOCKS_ML_GRADIENT =
  "linear-gradient(90deg, #ff4a22, #7a64ff, #005de4, #08c2d3)";

/** Its own file (not `sourceNames.ts`, which stays a plain constant) so
 * a plain-string consumer (e.g. an `aria-label`) can still read
 * `SOURCE_NAMES.ml` directly without pulling in JSX, and this file
 * -- which does export a component -- never mixes that with a
 * non-component export (`react-refresh/only-export-components`). */
export function SourceLabel({ source }: { readonly source: Source }) {
  if (source !== "ml") {
    return <>{SOURCE_NAMES[source]}</>;
  }
  return (
    <Box
      component="span"
      fw={700}
      style={{
        backgroundImage: GOLDILOCKS_ML_GRADIENT,
        backgroundClip: "text",
        WebkitBackgroundClip: "text",
        color: "transparent",
      }}
    >
      {SOURCE_NAMES.ml}
    </Box>
  );
}
