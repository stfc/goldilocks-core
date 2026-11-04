import {
  Box,
  Button,
  Group,
  Modal,
  Paper,
  SimpleGrid,
  Stack,
  Table,
  Text,
  Title,
  useComputedColorScheme,
} from "@mantine/core";
import { useEffect, useRef, useState } from "react";

import type { StructureInspection } from "../api/coreClient";
import { StructureFallback } from "./StructureFallback";
import { formatSiteCount } from "./siteCount";
import {
  attachStructureViewer,
  type StructureViewer,
  type StructureViewerFactory,
} from "./structureViewer";

const LATTICE_AXES = ["a", "b", "c"];
const LATTICE_ANGLES = ["α", "β", "γ"];

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
  const theme = useComputedColorScheme("light");
  const [detailsOpened, setDetailsOpened] = useState(false);

  useEffect(() => {
    const element = host.current;
    if (element === null) return;
    const lifetime = new AbortController();
    void (async () => {
      try {
        const created = await createViewer(element, lifetime.signal);
        if (lifetime.signal.aborted) {
          created.dispose();
          return;
        }
        viewer.current = created;
        created.refreshTheme();
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

  useEffect(() => {
    viewer.current?.refreshTheme();
  }, [theme]);

  const lattice = inspection.structure.lattice;
  const approximateOccupancies = inspection.structure.sites.some(
    (site) =>
      site.species.length !== 1 ||
      site.species.some((species) => species.occupancy !== 1),
  );
  return (
    <Box
      component="section"
      aria-label="Crystal structure viewer"
      style={{ display: "flex", flexDirection: "column" }}
      w="100%"
      h="100%"
    >
      <Box pos="relative" style={{ flex: 1, minHeight: 0 }}>
        <Box pos="absolute" inset={0} ref={host} />
        <StructureFallback
          structure={inspection.structure}
          containerRef={fallback}
          hidden
          onRetry={() => {
            setViewerRevision((revision) => revision + 1);
          }}
        />
        <Group pos="absolute" top={10} left={10} align="baseline" gap={6}>
          <Title order={3}>{inspection.structure.reduced_formula}</Title>
          <Text size="xs" c="dimmed">
            {formatSiteCount(inspection.structure.site_count, "atomic site")}
          </Text>
        </Group>
      </Box>
      <Stack gap={6} mt={6}>
        {approximateOccupancies ? (
          <Text size="xs" c="dimmed" role="note">
            Mixed or partial occupancy: this 3D preview is an approximation.
            Inspect the canonical site details for the exact species and
            occupancies.
          </Text>
        ) : null}
        <Button
          size="compact-sm"
          fullWidth
          styles={{ label: { whiteSpace: "normal" } }}
          onClick={() => {
            setDetailsOpened(true);
          }}
        >
          Inspect lattice, sites and occupancies
        </Button>
      </Stack>
      <Modal
        opened={detailsOpened}
        onClose={() => {
          setDetailsOpened(false);
        }}
        title="Lattice, sites and occupancies"
        size="lg"
        closeButtonProps={{ "aria-label": "Close canonical site details" }}
      >
        {detailsOpened ? (
          <Stack>
            <Text size="sm">
              Canonical inspection data. Occupancies are fractions of each site;
              coordinates are fractional lattice coordinates.
            </Text>
            <Paper
              component="section"
              aria-label="Lattice parameters"
              p="sm"
              withBorder
            >
              <Title order={4} mb="xs">
                Lattice parameters
              </Title>
              <SimpleGrid component="dl" cols={3} spacing="md" m={0}>
                {lattice.lengths_angstrom.map((length, index) => (
                  <div key={index}>
                    <dt>{LATTICE_AXES[index]}</dt>
                    <dd>{length.toFixed(3)} Å</dd>
                  </div>
                ))}
                {lattice.angles_degrees.map((angle, index) => (
                  <div key={index}>
                    <dt>{LATTICE_ANGLES[index]}</dt>
                    <dd>{angle.toFixed(3)}°</dd>
                  </div>
                ))}
                <div>
                  <dt>V</dt>
                  <dd>{lattice.volume_angstrom3.toFixed(2)} Å³</dd>
                </div>
              </SimpleGrid>
            </Paper>
            {inspection.structure.sites.map((site, index) => (
              <Paper
                component="section"
                aria-label={`Site ${String(index + 1)}`}
                key={index}
                p="sm"
                withBorder
              >
                <Title order={3}>Site {index + 1}</Title>
                <Text size="sm" style={{ overflowWrap: "anywhere" }}>
                  Fractional coordinates:{" "}
                  {site.fractional_coordinates.join(", ")}
                </Text>
                <Table layout="fixed" style={{ overflowWrap: "anywhere" }}>
                  <Table.Thead>
                    <Table.Tr>
                      <Table.Th scope="col">Species</Table.Th>
                      <Table.Th scope="col">Element</Table.Th>
                      <Table.Th scope="col">Occupancy</Table.Th>
                    </Table.Tr>
                  </Table.Thead>
                  <Table.Tbody>
                    {site.species.map((species, speciesIndex) => (
                      <Table.Tr key={speciesIndex}>
                        <Table.Th scope="row">{species.label}</Table.Th>
                        <Table.Td>{species.symbol}</Table.Td>
                        <Table.Td>{species.occupancy}</Table.Td>
                      </Table.Tr>
                    ))}
                  </Table.Tbody>
                </Table>
              </Paper>
            ))}
          </Stack>
        ) : null}
      </Modal>
    </Box>
  );
}
