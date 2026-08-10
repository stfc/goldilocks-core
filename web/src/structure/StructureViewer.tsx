import { Alert, Badge, Group, Stack, Table, Text } from '@mantine/core';
import type { StructureDocument } from '../client/types';

interface SiteRow {
  label: string;
  species: string;
  xyz: string;
}

function siteRows(structure: StructureDocument): SiteRow[] {
  return structure.sites.map((site) => ({
    label: site.label,
    species: site.species
      .map((s) => `${s.element}${s.occupancy !== 1 ? `×${s.occupancy}` : ''}`)
      .join(' + '),
    xyz: site.xyz.map((v) => v.toFixed(3)).join(', '),
  }));
}

function hasDisorder(structure: StructureDocument): boolean {
  return structure.sites.some(
    (site) => site.species.length > 1 || site.species.some((s) => s.occupancy < 1),
  );
}

/**
 * Library-neutral structure presentation.
 *
 * Consumes a `StructureDocument`; no 3D library object or event type crosses
 * this seam. This slice ships the textual fallback (a site table with disorder
 * disclosure). A lazy 3D adapter lands behind the same component after the
 * viewer lifecycle spike proves canvases and WebGL resources are released.
 */
export function StructureViewer({ structure }: { structure: StructureDocument }) {
  const rows = siteRows(structure);
  const disordered = hasDisorder(structure);

  return (
    <Stack gap="sm">
      <Group gap="xs">
        <Text size="sm" c="dimmed">
          Structure viewer
        </Text>
        {disordered && (
          <Badge variant="light" color="stone">
            Mixed occupancy
          </Badge>
        )}
      </Group>

      {disordered && (
        <Alert title="Mixed occupancy" color="gold">
          Some sites carry partial or mixed occupancy. The canonical structure preserves
          every species and occupancy exactly; the 3D representation will approximate
          these sites and should be read alongside this table.
        </Alert>
      )}

      <Table withTableBorder highlightOnHover stickyHeader>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Site</Table.Th>
            <Table.Th>Species</Table.Th>
            <Table.Th>Cartesian (Å)</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {rows.map((row, index) => (
            // Key by index: site labels are not guaranteed unique across a
            // structure (mixed occupancy can repeat a label).
            <Table.Tr key={index}>
              <Table.Td>{row.label}</Table.Td>
              <Table.Td>{row.species}</Table.Td>
              <Table.Td>{row.xyz}</Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Stack>
  );
}
