import { Alert, Button, Text } from "@mantine/core";
import type { Ref } from "react";

import type { StructureInspection } from "../api/coreClient";

export function StructureFallback({
  structure,
  onRetry,
  containerRef,
  hidden = false,
}: {
  readonly structure: StructureInspection["structure"];
  readonly onRetry: () => void;
  readonly containerRef?: Ref<HTMLDivElement>;
  readonly hidden?: boolean;
}) {
  const siteLabel =
    structure.site_count === 1
      ? "1 atomic site"
      : `${String(structure.site_count)} atomic sites`;
  return (
    <Alert
      ref={containerRef}
      title="3D structure preview unavailable"
      pos="absolute"
      top="25%"
      left="10%"
      right="10%"
      style={{ zIndex: 5 }}
      hidden={hidden}
      role="status"
      aria-live="polite"
    >
      <Text>
        {structure.reduced_formula} · {siteLabel}
      </Text>
      <Text size="sm" mt="sm">
        The parsed structure and recommendation remain available without the
        interactive preview.
      </Text>
      <Button mt="md" variant="light" onClick={onRetry}>
        Retry 3D preview
      </Button>
    </Alert>
  );
}
