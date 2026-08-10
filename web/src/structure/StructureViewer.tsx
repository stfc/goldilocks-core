import {
  Alert,
  Badge,
  Box,
  Button,
  Card,
  Group,
  Loader,
  SegmentedControl,
  Stack,
  Switch,
  Table,
  Text,
  Title,
} from '@mantine/core';
import { IconFocusCentered, IconPhoto } from '@tabler/icons-react';
import { useEffect, useRef, useState } from 'react';
import type { StructureDocument } from '../client/types';
import {
  DEFAULT_VIEWER_OPTIONS,
  type CrystalViewerAdapter,
  type CrystalViewerAdapterFactory,
  type ViewerOptions,
  type ViewerRepresentation,
} from './CrystalViewer';
import { createThreeDmolAdapter } from './ThreeDmolViewer';

type ViewerStatus = 'loading' | 'ready' | 'error';

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

function friendlyError(reason: unknown): string {
  if (reason instanceof Error && reason.message) return reason.message;
  return 'The 3D renderer could not start.';
}

function parseRepetitions(value: string): readonly [number, number, number] {
  const [a, b, c] = value.split('×').map(Number);
  return [a || 1, b || 1, c || 1];
}

const REPETITION_OPTIONS = ['1×1×1', '2×2×2', '3×3×3'];

/**
 * Textual site table — the dependency-free fallback shown when the 3D renderer
 * fails, preserving every species and occupancy from the canonical structure.
 */
function SiteTable({ structure }: { structure: StructureDocument }) {
  const rows = siteRows(structure);
  return (
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
  );
}

interface StructureViewerProps {
  structure: StructureDocument;
  /** Defaults to the real 3Dmol adapter; tests inject a fake at this seam. */
  adapterFactory?: CrystalViewerAdapterFactory;
}

/**
 * Library-neutral structure viewer panel.
 *
 * Consumes a `StructureDocument`; no 3D library object or event type crosses
 * this seam. A lazy 3D adapter renders the crystal behind a narrow lifecycle;
 * loading, WebGL/library failure (with a textual fallback), and disorder are
 * surfaced without crashing the shell.
 */
export function StructureViewer({
  structure,
  adapterFactory = createThreeDmolAdapter,
}: StructureViewerProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const adapterRef = useRef<CrystalViewerAdapter | null>(null);
  const [status, setStatus] = useState<ViewerStatus>('loading');
  const [error, setError] = useState<string | null>(null);
  const [options, setOptionsState] = useState<ViewerOptions>(DEFAULT_VIEWER_OPTIONS);

  // One adapter per mounted container. Structure or factory changes dispose the
  // old adapter and mount a fresh one; a stale async load is discarded via the
  // `cancelled` guard and the adapter's own invalidation on dispose.
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    let cancelled = false;
    const adapter = adapterFactory(container);
    adapterRef.current = adapter;
    setStatus('loading');
    setError(null);
    adapter
      .load(structure)
      .then(() => {
        if (!cancelled) setStatus('ready');
      })
      .catch((reason: unknown) => {
        if (!cancelled) {
          setStatus('error');
          setError(friendlyError(reason));
        }
      });
    return () => {
      cancelled = true;
      adapter.dispose();
      adapterRef.current = null;
    };
  }, [structure, adapterFactory]);

  // Keep the live adapter's presentation options in sync with the controls.
  useEffect(() => {
    adapterRef.current?.setOptions(options);
  }, [options]);

  const setOptions = (patch: Partial<ViewerOptions>) =>
    setOptionsState((prev) => ({ ...prev, ...patch }));

  const disordered = hasDisorder(structure);

  const handleExportPng = async () => {
    const pending = adapterRef.current?.exportPng();
    if (!pending) return;
    try {
      const blob = await pending;
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = `${structure.reduced_formula || 'structure'}.png`;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch {
      // PNG export unavailable (e.g. renderer already gone); stay inert.
    }
  };

  return (
    <Card withBorder radius="md" padding={0}>
      <Stack gap="sm">
        <Group justify="space-between" align="baseline" px="lg" pt="lg" pb={0}>
          <Group gap="sm" align="baseline">
            <Title order={2}>Structure</Title>
            <Badge variant="light" color="gold">
              {structure.reduced_formula}
            </Badge>
          </Group>
          {disordered && (
            <Badge variant="light" color="stone">
              Mixed occupancy
            </Badge>
          )}
        </Group>

        {disordered && (
          <Box px="lg">
            <Alert color="gold" title="Mixed occupancy">
              Some sites carry partial or mixed occupancy. The canonical structure
              preserves every species and occupancy exactly; the 3D view approximates
              these sites by their dominant species and should be read alongside the
              textual site list.
            </Alert>
          </Box>
        )}

        <Box px="lg" pb="sm">
          <Box h={380} pos="relative" style={{ overflow: 'hidden' }}>
            {status !== 'error' && (
              <div
                ref={containerRef}
                role={status === 'ready' ? 'img' : undefined}
                aria-label={status === 'ready' ? '3D structure viewer' : undefined}
                aria-hidden={status !== 'ready'}
                style={{ position: 'absolute', inset: 0 }}
              />
            )}

            {status === 'loading' && (
              <Box
                pos="absolute"
                inset={0}
                style={{ display: 'grid', placeItems: 'center' }}
                role="status"
              >
                <Group gap="sm">
                  <Loader size="sm" />
                  <Text size="sm" c="dimmed">
                    Loading 3D viewer…
                  </Text>
                </Group>
              </Box>
            )}

            {status === 'error' && (
              <Stack gap="sm" p="sm">
                <Alert color="red" title="Could not render the 3D view">
                  <Text size="sm">{error}</Text>
                </Alert>
                <Box style={{ maxHeight: 280, overflow: 'auto' }}>
                  <SiteTable structure={structure} />
                </Box>
              </Stack>
            )}
          </Box>
        </Box>

        {status === 'ready' && (
          <Stack gap="sm" px="lg" pb="lg">
            <Group justify="space-between" wrap="wrap" gap="sm">
              <SegmentedControl
                value={options.representation}
                onChange={(value) =>
                  setOptions({ representation: value as ViewerRepresentation })
                }
                data={[
                  { label: 'Ball & stick', value: 'ball-stick' },
                  { label: 'Spacefill', value: 'spacefill' },
                ]}
                aria-label="Representation"
              />
              <SegmentedControl
                value={options.repetitions.join('×')}
                onChange={(value) =>
                  setOptions({ repetitions: parseRepetitions(value) })
                }
                data={REPETITION_OPTIONS.map((value) => ({ label: value, value }))}
                aria-label="Replication"
              />
            </Group>

            <Group justify="space-between" wrap="wrap" gap="sm">
              <Switch
                label="Unit cell"
                checked={options.showCell}
                onChange={(event) =>
                  setOptions({ showCell: event.currentTarget.checked })
                }
              />
              <Group gap="sm">
                <Button
                  variant="default"
                  size="xs"
                  leftSection={<IconFocusCentered size={15} />}
                  onClick={() => adapterRef.current?.resetCamera()}
                >
                  Reset view
                </Button>
                <Button
                  variant="default"
                  size="xs"
                  leftSection={<IconPhoto size={15} />}
                  onClick={() => void handleExportPng()}
                >
                  Export PNG
                </Button>
              </Group>
            </Group>
          </Stack>
        )}
      </Stack>
    </Card>
  );
}
