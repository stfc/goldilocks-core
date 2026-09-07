import { Box, Group, Paper, SimpleGrid, Text, Title } from "@mantine/core";
import { useEffect, useRef, useState } from "react";

import type { StructureInspection } from "../api/coreClient";
import { StructureFallback } from "./StructureFallback";
import {
  attachStructureViewer,
  type StructureViewer,
  type StructureViewerFactory,
} from "./structureViewer";

const LATTICE_AXES = ["a", "b", "c"];

export function StructureViewport({
  inspection,
  createViewer = attachStructureViewer,
}: {
  readonly inspection: StructureInspection;
  readonly createViewer?: StructureViewerFactory;
}) {
  const host = useRef<HTMLDivElement>(null);
  const viewer = useRef<StructureViewer | null>(null);
  const canonicalCif = useRef(inspection.canonical_cif);
  const fallback = useRef<HTMLDivElement>(null);
  const [viewerRevision, setViewerRevision] = useState(0);

  useEffect(() => {
    const element = host.current;
    if (element === null) return;
    const lifetime = new AbortController();
    void (async () => {
      try {
        const created = await createViewer(element);
        if (lifetime.signal.aborted) {
          created.dispose();
          return;
        }
        viewer.current = created;
        created.show(canonicalCif.current);
        if (fallback.current !== null) fallback.current.hidden = true;
      } catch {
        if (!lifetime.signal.aborted && fallback.current !== null) {
          fallback.current.hidden = false;
        }
      }
    })();
    return () => {
      lifetime.abort();
      viewer.current?.dispose();
      viewer.current = null;
    };
  }, [createViewer, viewerRevision]);

  useEffect(() => {
    canonicalCif.current = inspection.canonical_cif;
    if (viewer.current === null) return;
    try {
      viewer.current.show(inspection.canonical_cif);
      if (fallback.current !== null) fallback.current.hidden = true;
    } catch {
      if (fallback.current !== null) fallback.current.hidden = false;
    }
  }, [inspection.canonical_cif]);

  const lattice = inspection.structure.lattice;
  return (
    <Box
      component="section"
      aria-label="Crystal structure viewer"
      pos="relative"
      w="100%"
      h="100%"
    >
      <Box pos="absolute" inset={0} ref={host} />
      <StructureFallback
        structure={inspection.structure}
        containerRef={fallback}
        hidden
        onRetry={() => {
          setViewerRevision((revision) => revision + 1);
        }}
      />
      <Group pos="absolute" top={16} left={16} align="baseline">
        <Title order={2}>{inspection.structure.reduced_formula}</Title>
        <Text size="sm">{inspection.structure.site_count} atomic sites</Text>
      </Group>
      <Paper pos="absolute" right={16} bottom={16} p="sm" withBorder>
        <SimpleGrid component="dl" cols={2} spacing="md" m={0}>
          {lattice.lengths_angstrom.map((length, index) => (
            <div key={index}>
              <dt>{LATTICE_AXES[index]}</dt>
              <dd>{length.toFixed(3)} Å</dd>
            </div>
          ))}
          <div>
            <dt>V</dt>
            <dd>{lattice.volume_angstrom3.toFixed(2)} Å³</dd>
          </div>
        </SimpleGrid>
      </Paper>
    </Box>
  );
}
