import { Card, Stack, Text, Title } from '@mantine/core';

function NetworkGlyph() {
  return (
    <svg
      width="44"
      height="44"
      viewBox="0 0 44 44"
      aria-hidden="true"
      focusable="false"
    >
      <g fill="none" stroke="var(--mantine-color-gold-6)" strokeWidth="2">
        <circle cx="12" cy="12" r="4" />
        <circle cx="32" cy="12" r="4" />
        <circle cx="22" cy="32" r="4" />
        <line x1="15" y1="14" x2="29" y2="29" />
        <line x1="29" y1="14" x2="25" y2="29" />
        <line x1="15" y1="14" x2="19" y2="29" />
      </g>
    </svg>
  );
}

/**
 * Graph view placeholder for the foundation slice.
 *
 * The full backend-driven Graph view (automatic layout, selected-vs-required
 * records, record execution) lands in a later slice. This placeholder keeps the
 * view switch honest and the shell complete.
 */
export function GraphView() {
  return (
    <Card withBorder radius="md">
      <Stack align="center" justify="center" gap="sm" py="xl" ta="center">
        <NetworkGlyph />
        <Title order={3}>Task Graph</Title>
        <Text size="sm" c="dimmed" maw={420}>
          The Graph view inspects the backend-owned task topology, selects the records
          you want computed, and distinguishes them from required dependency stages. It
          arrives in a later slice; the Guided view is fully wired today.
        </Text>
      </Stack>
    </Card>
  );
}
