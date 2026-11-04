import type { Source } from "./coreClient";

/** Shared between `ScientificRecord` (records) and `OverrideControl`
 * (the control bound to one of those records) -- its own file, not
 * exported from either component, so neither trips
 * react-refresh/only-export-components. */
export const SOURCE_NAMES: Record<Source, string> = {
  human: "Your override",
  ml: "Goldilocks-ML prediction",
  llm: "LLM suggestion",
  heuristic: "Heuristic default",
};
