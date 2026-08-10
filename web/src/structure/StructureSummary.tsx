import { Badge, Card, Group, Stack, Table, Text, Title } from '@mantine/core';
import type { StructureDocument } from '../client/types';

function uniqueElements(structure: StructureDocument): string {
  const elements = new Set<string>();
  for (const site of structure.sites) {
    for (const species of site.species) {
      elements.add(species.element);
    }
  }
  return elements.size > 0 ? [...elements].sort().join(', ') : '—';
}

/** Textual, dependency-free summary of a canonical Structure Document. */
export function StructureSummary({ structure }: { structure: StructureDocument }) {
  const { lattice } = structure;
  const elements = uniqueElements(structure);

  return (
    <Card withBorder radius="md" p="md">
      <Stack gap="sm">
        <Group justify="space-between" align="baseline">
          <Title order={2}>{structure.formula}</Title>
          <Badge variant="light" color="gold">
            {structure.reduced_formula}
          </Badge>
        </Group>
        <Text size="sm" c="dimmed">
          {structure.sites.length} sites · {elements}
        </Text>

        <Table variant="vertical" withTableBorder highlightOnHover>
          <Table.Tbody>
            <Table.Tr>
              <Table.Th>Lattice a / b / c (Å)</Table.Th>
              <Table.Td>
                {lattice.a.toFixed(3)} / {lattice.b.toFixed(3)} / {lattice.c.toFixed(3)}
              </Table.Td>
            </Table.Tr>
            <Table.Tr>
              <Table.Th>α / β / γ (°)</Table.Th>
              <Table.Td>
                {lattice.alpha.toFixed(2)} / {lattice.beta.toFixed(2)} /{' '}
                {lattice.gamma.toFixed(2)}
              </Table.Td>
            </Table.Tr>
            <Table.Tr>
              <Table.Th>Volume (Å³)</Table.Th>
              <Table.Td>{lattice.volume.toFixed(3)}</Table.Td>
            </Table.Tr>
            <Table.Tr>
              <Table.Th>Periodic boundaries</Table.Th>
              <Table.Td>
                {lattice.pbc.map((v) => (v ? 'on' : 'off')).join(' / ')}
              </Table.Td>
            </Table.Tr>
          </Table.Tbody>
        </Table>
      </Stack>
    </Card>
  );
}
