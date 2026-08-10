import {
  Alert,
  Badge,
  Box,
  Button,
  Card,
  Collapse,
  Divider,
  FileInput,
  Group,
  Loader,
  NumberInput,
  Select,
  SimpleGrid,
  Stack,
  Text,
  Textarea,
  TextInput,
  Title,
  UnstyledButton,
} from '@mantine/core';
import { IconArrowRight, IconFileZip } from '@tabler/icons-react';
import { useState } from 'react';
import { ErrorReport } from '../../errors/ErrorReport';
import { useWorkspace, useWorkspaceStore } from '../../store/WorkspaceContext';
import type { SmearingType, StructureFormat, VdwMethod } from '../../client/types';
import { presentRecommendation } from '../../records/presenters';
import { RawJson } from '../../records/RawJson';
import { downloadInputArchive } from '../../archive/InputArchive';
import { StructureSummary } from '../../structure/StructureSummary';
import { StructureViewer } from '../../structure/StructureViewer';

export function detectFormat(content: string): StructureFormat | undefined {
  const lines = content.split(/\r?\n/);
  // CIF: a `data_` block may follow leading `#` comment lines, so scan every
  // line rather than only checking the first.
  if (lines.some((line) => line.trimStart().startsWith('data_'))) return 'cif';
  // POSCAR: the first meaningful line is a comment and the next is a numeric
  // scale factor, so it survives a leading comment or blank line.
  const meaningful = lines.map((line) => line.trim()).filter(Boolean);
  if (
    meaningful.length >= 2 &&
    /^[+-]?\d+(\.\d+)?([eE][+-]?\d+)?$/.test(meaningful[1])
  ) {
    return 'poscar';
  }
  return undefined;
}

function readFileAsText(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(new Error(`Could not read ${file.name}.`));
    reader.readAsText(file);
  });
}

/** Structure upload surface: paste, file picker, or drag/drop. */
function StructureSourcePanel() {
  const loadStructure = useWorkspace((s) => s.loadStructure);
  const structureStatus = useWorkspace((s) => s.structureStatus);
  const structureFailure = useWorkspace((s) => s.structureFailure);
  const [text, setText] = useState('');
  const [loading, setLoading] = useState(false);
  const [dragging, setDragging] = useState(false);

  const run = async (content: string) => {
    setText(content);
    setLoading(true);
    try {
      await loadStructure({ content, format: detectFormat(content) });
    } finally {
      setLoading(false);
    }
  };

  const dropFile = async (file: File | undefined) => {
    if (!file) return;
    const content = await readFileAsText(file);
    await run(content);
  };

  const busy = structureStatus === 'running' || loading;

  return (
    <Card
      withBorder
      radius="md"
      onDragOver={(event) => {
        event.preventDefault();
        if (event.dataTransfer) event.dataTransfer.dropEffect = 'copy';
        setDragging(true);
      }}
      onDragLeave={(event) => {
        // Leave only when the pointer exits this panel, not its children.
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
          setDragging(false);
        }
      }}
      onDrop={(event) => {
        event.preventDefault();
        setDragging(false);
        void dropFile(event.dataTransfer.files?.[0]);
      }}
      style={{
        outline: dragging ? '2px dashed var(--mantine-color-gold-6)' : undefined,
        outlineOffset: -2,
      }}
    >
      <Stack gap="sm">
        <div>
          <Title order={2}>Load a structure</Title>
          <Text size="sm" c="dimmed">
            Paste CIF or POSCAR content, pick a file, or drop one anywhere on this
            panel. Your file stays in the browser and is never read from a server path.
          </Text>
        </div>

        <Textarea
          label="Structure content"
          placeholder="Paste CIF or POSCAR…"
          value={text}
          onChange={(event) => setText(event.currentTarget.value)}
          minRows={8}
          maxRows={14}
          autosize
        />

        <Group justify="space-between" wrap="wrap" gap="sm">
          <FileInput
            accept=".cif,.poscar,text/plain"
            placeholder="Choose a file…"
            clearable
            onChange={(file) => void dropFile(file ?? undefined)}
          />
          <Text size="xs" c="dimmed">
            or drop a file anywhere on this panel
          </Text>

          <Button
            onClick={() => void run(text)}
            loading={busy}
            loaderProps={{ type: 'dots' }}
            disabled={text.trim().length === 0}
            rightSection={<IconArrowRight size={16} />}
          >
            Load structure
          </Button>
        </Group>

        {structureStatus === 'failed' && structureFailure !== null && (
          <ErrorReport failure={structureFailure} />
        )}
      </Stack>
    </Card>
  );
}

/** Recommended parameters and records presented for review. */
function RecommendationPanel() {
  const records = useWorkspace((s) => s.records);
  const recordsStatus = useWorkspace((s) => s.recordsStatus);
  const recordsFailure = useWorkspace((s) => s.recordsFailure);
  const recordsStale = useWorkspace((s) => s.recordsStale);

  if (recordsStatus === 'running' && records === null) {
    return (
      <Card withBorder radius="md" role="status">
        <Group justify="center" gap="sm" py="lg">
          <Loader size="sm" />
          <Text size="sm" c="dimmed">
            Running recommendation…
          </Text>
        </Group>
      </Card>
    );
  }

  if (recordsStatus === 'failed' && records === null) {
    return (
      <Card withBorder radius="md">
        <Stack gap="sm">
          <Title order={2}>Recommendation</Title>
          {recordsFailure !== null && <ErrorReport failure={recordsFailure} />}
          <Text size="sm" c="dimmed">
            The recommendation did not complete. Your structure and any prior results
            remain available — fix the override and retry without re-uploading.
          </Text>
        </Stack>
      </Card>
    );
  }

  if (records === null) {
    return null;
  }

  const presented = presentRecommendation(records);
  const busy = recordsStatus === 'running';

  return (
    <Card withBorder radius="md" className="panel-enter">
      <Stack gap="md">
        <Group justify="space-between" align="baseline">
          <Group gap="sm" align="baseline">
            <Title order={2}>Recommendation</Title>
            <Badge variant="light" color="gold">
              {presented.reducedFormula}
            </Badge>
            {recordsStale && (
              <Badge variant="light" color="ink">
                Stale
              </Badge>
            )}
          </Group>
          {busy && <Loader size="sm" />}
        </Group>

        {presented.warnings.length > 0 && (
          <Alert color="gold" title="Warnings">
            <Stack gap={4}>
              {presented.warnings.map((warning, index) => (
                <Text key={index} size="sm">
                  {warning}
                </Text>
              ))}
            </Stack>
          </Alert>
        )}

        <SimpleGrid cols={{ base: 1, sm: 2, lg: 2 }} spacing="md">
          {presented.sections.map((section) => (
            <Card
              key={section.id}
              withBorder
              radius="md"
              bg="var(--mantine-color-stone-0)"
            >
              <Stack gap="xs">
                <Title order={3}>{section.title}</Title>
                {section.values.map((value) => (
                  <div key={value.label}>
                    <Group justify="space-between" gap="md" align="baseline">
                      <Text size="sm" c="dimmed">
                        {value.label}
                      </Text>
                      <Text size="sm" fw={600} ta="right" ff="monospace">
                        {value.value}
                        {value.unit ? ` ${value.unit}` : ''}
                      </Text>
                    </Group>
                    {value.provenance?.reason && (
                      <Text size="xs" c="dimmed" mt={2}>
                        {value.provenance.reason}
                      </Text>
                    )}
                  </div>
                ))}
                {section.provenance && (
                  <Text size="xs" c="dimmed">
                    {section.provenance.reason}
                  </Text>
                )}
                <Divider mt="xs" />
                <RawJson name={section.id} value={section.raw} />
              </Stack>
            </Card>
          ))}
        </SimpleGrid>
      </Stack>
    </Card>
  );
}

const SMEARING_OPTIONS: Array<{ value: string; label: string }> = [
  { value: '', label: 'Let Goldilocks decide' },
  { value: 'cold', label: 'cold' },
  { value: 'gaussian', label: 'gaussian' },
  { value: 'mp', label: 'mp' },
  { value: 'fixed', label: 'fixed' },
];

const VDW_METHOD_OPTIONS: Array<{ value: string; label: string }> = [
  { value: '', label: 'Let Goldilocks decide' },
  { value: 'd3', label: 'DFT-D3' },
  { value: 'd3bj', label: 'DFT-D3(BJ)' },
  { value: 'ts', label: 'TS' },
  { value: 'mbd', label: 'MBD' },
];

/** A three-way boolean override: decide, force on, or force off. */
function TriSelect({
  label,
  value,
  onChange,
}: {
  label: string;
  value: boolean | null | undefined;
  onChange: (value: boolean | null) => void;
}) {
  return (
    <Select
      label={label}
      allowDeselect
      data={[
        { value: '', label: 'Let Goldilocks decide' },
        { value: 'true', label: 'Yes' },
        { value: 'false', label: 'No' },
      ]}
      value={value === null || value === undefined ? '' : String(value)}
      onChange={(next) => onChange(next === '' ? null : next === 'true')}
    />
  );
}

/** A numeric hint with a scientific unit; blank leaves it to Core. */
function NumberHint({
  label,
  unit,
  value,
  onChange,
  integer = false,
}: {
  label: string;
  unit?: string;
  value: number | null | undefined;
  onChange: (value: number | null) => void;
  integer?: boolean;
}) {
  return (
    <NumberInput
      label={unit ? `${label} (${unit})` : label}
      value={value ?? ''}
      onChange={(next) => {
        if (next === '' || next === null) {
          onChange(null);
          return;
        }
        const parsed = typeof next === 'number' ? next : Number(next);
        onChange(
          Number.isFinite(parsed) ? (integer ? Math.round(parsed) : parsed) : null,
        );
      }}
      placeholder="Let Goldilocks decide"
    />
  );
}

/** Supported overrides on Intent and Calculation Hints. */
function OverridesPanel() {
  const intent = useWorkspace((s) => s.intent);
  const hints = useWorkspace((s) => s.hints);
  const setIntent = useWorkspace((s) => s.setIntent);
  const setHints = useWorkspace((s) => s.setHints);
  const [open, setOpen] = useState(false);

  return (
    <Card withBorder radius="md">
      <UnstyledButton
        onClick={() => setOpen((v) => !v)}
        w="100%"
        aria-expanded={open}
        aria-controls="calculation-overrides"
      >
        <Group justify="space-between">
          <Text fw={600}>Calculation overrides</Text>
          <Text size="xs" c="dimmed">
            {open ? 'hide' : 'show'}
          </Text>
        </Group>
      </UnstyledButton>
      <Collapse expanded={open}>
        <Stack gap="md" mt="md" id="calculation-overrides">
          <div>
            <Title order={3}>Functional</Title>
            <Select
              label="Exchange–correlation functional"
              data={['PBEsol', 'PBE', 'LDA']}
              value={intent.functional}
              onChange={(value) => value && setIntent({ functional: value })}
            />
          </div>

          <Divider />

          <div>
            <Title order={3}>k-points</Title>
            <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="sm">
              <NumberHint
                label="Spacing"
                unit="Å⁻¹"
                value={hints.k_spacing}
                onChange={(value) => setHints({ k_spacing: value })}
              />
              <TextInputGrid
                label="Grid"
                value={hints.k_grid}
                onChange={(value) => setHints({ k_grid: value })}
              />
            </SimpleGrid>
          </div>

          <Divider />

          <div>
            <Title order={3}>Smearing</Title>
            <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="sm">
              <Select
                label="Smearing type"
                data={SMEARING_OPTIONS}
                value={hints.smearing_type ?? ''}
                onChange={(next) =>
                  setHints({
                    smearing_type: next ? (next as SmearingType) : null,
                  })
                }
              />
              <NumberHint
                label="Smearing width"
                unit="Ry"
                value={hints.smearing_width_ry}
                onChange={(value) => setHints({ smearing_width_ry: value })}
              />
            </SimpleGrid>
          </div>

          <Divider />

          <div>
            <Title order={3}>Magnetism &amp; relativity</Title>
            <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="sm">
              <TriSelect
                label="Spin polarised"
                value={hints.spin_polarized}
                onChange={(value) => setHints({ spin_polarized: value })}
              />
              <TriSelect
                label="Spin–orbit coupling"
                value={hints.spin_orbit_coupling}
                onChange={(value) => setHints({ spin_orbit_coupling: value })}
              />
              <Select
                label="Relativistic treatment"
                allowDeselect
                data={[
                  { value: '', label: 'Let Goldilocks decide' },
                  { value: 'scalar', label: 'Scalar' },
                  { value: 'full', label: 'Full' },
                  { value: 'non-relativistic', label: 'Non-relativistic' },
                ]}
                value={hints.relativistic_mode ?? ''}
                onChange={(next) => setHints({ relativistic_mode: next || null })}
              />
            </SimpleGrid>
          </div>

          <Divider />

          <div>
            <Title order={3}>Convergence</Title>
            <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="sm">
              <NumberHint
                label="Convergence threshold"
                unit="Ry"
                value={hints.conv_thr}
                onChange={(value) => setHints({ conv_thr: value })}
              />
              <NumberHint
                label="Mixing beta"
                value={hints.mixing_beta}
                onChange={(value) => setHints({ mixing_beta: value })}
              />
              <NumberHint
                label="Max SCF steps"
                value={hints.electron_maxstep}
                integer
                onChange={(value) => setHints({ electron_maxstep: value })}
              />
            </SimpleGrid>
          </div>

          <Divider />

          <div>
            <Title order={3}>Dispersion</Title>
            <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="sm">
              <TriSelect
                label="Dispersion correction"
                value={hints.use_vdw}
                onChange={(value) => setHints({ use_vdw: value })}
              />
              <Select
                label="Dispersion method"
                data={VDW_METHOD_OPTIONS}
                value={hints.vdw_method ?? ''}
                onChange={(next) =>
                  setHints({ vdw_method: next ? (next as VdwMethod) : null })
                }
              />
            </SimpleGrid>
          </div>

          <Text size="xs" c="dimmed">
            Changing a value marks existing recommendations and generated inputs stale
            until you re-run the recommendation and regenerate the archive.
          </Text>
        </Stack>
      </Collapse>
    </Card>
  );
}

/** A space-separated k-point grid override, e.g. `4 4 4`. */
function TextInputGrid({
  label,
  value,
  onChange,
}: {
  label: string;
  value: number[] | null | undefined;
  onChange: (value: number[] | null) => void;
}) {
  return (
    <TextInput
      label={label}
      placeholder="e.g. 4 4 4"
      value={value ? value.join(' ') : ''}
      onChange={(event) => {
        const parts = event.currentTarget.value.trim().split(/\s+/).filter(Boolean);
        const parsed = parts.map(Number);
        const valid = parts.length > 0 && parsed.every((n) => Number.isFinite(n));
        onChange(valid ? parsed : null);
      }}
    />
  );
}

/** Explicit generate action after recommendation review: builds and downloads
 * the formula-named input archive, keeping failures local. */
function GenerationPanel() {
  const store = useWorkspaceStore();
  const records = useWorkspace((s) => s.records);
  const generationStatus = useWorkspace((s) => s.generationStatus);
  const generationFailure = useWorkspace((s) => s.generationFailure);
  const generatedStale = useWorkspace((s) => s.generatedStale);

  if (records === null) return null;

  const busy = generationStatus === 'running';

  const handleGenerate = async () => {
    await store.getState().generate();
    const s = store.getState();
    if (
      s.generationStatus !== 'complete' ||
      !s.generated ||
      !s.structure ||
      !s.source ||
      !s.records
    ) {
      return;
    }
    downloadInputArchive({
      files: s.generated.generated_files,
      structure: s.structure,
      request: { structure: s.source, intent: s.intent, hints: s.hints },
      recommendation: s.records,
      meta: {
        generatedBy: 'goldilocks-workbench',
        createdAt: new Date().toISOString(),
      },
    });
  };

  return (
    <Card withBorder radius="md" className="panel-enter">
      <Stack gap="md">
        <Group justify="space-between" align="baseline">
          <div>
            <Title order={2}>Input archive</Title>
            <Text size="sm" c="dimmed">
              Bundle the generated Quantum ESPRESSO inputs, the original structure, and
              a reproducibility manifest into one downloadable ZIP.
            </Text>
          </div>
          {generatedStale && (
            <Badge variant="light" color="ink">
              Stale
            </Badge>
          )}
          {busy && <Loader size="sm" />}
        </Group>

        {generationStatus === 'failed' && generationFailure !== null && (
          <Stack gap="sm">
            <ErrorReport failure={generationFailure} />
            <Text size="sm" c="dimmed">
              Generation did not complete. Your recommendation and structure remain
              available — fix the inputs and retry without re-uploading.
            </Text>
          </Stack>
        )}

        <Group>
          <Button
            onClick={() => void handleGenerate()}
            leftSection={<IconFileZip size={16} />}
            loading={busy}
            loaderProps={{ type: 'dots' }}
          >
            Generate input archive
          </Button>
          {busy && (
            <Text size="sm" c="dimmed">
              Bundling inputs…
            </Text>
          )}
        </Group>
      </Stack>
    </Card>
  );
}

const STEPS = [
  { n: '1', label: 'Load a CIF or POSCAR structure' },
  { n: '2', label: 'Review recommendations, provenance, and overrides' },
  { n: '3', label: 'Download one reproducible input archive' },
];

/** Designed empty state: explains the three-step flow before a structure is
 * loaded. Numbers + labels carry the order, never colour alone. */
function GuidedWelcome() {
  return (
    <Card withBorder radius="md" p="xl" className="panel-enter">
      <Stack gap="md">
        <div>
          <Title order={2}>Structure in, reviewed calculation input out</Title>
          <Text size="sm" c="dimmed" mt={4}>
            Goldilocks turns a crystal structure into a recommended, reproducible
            Quantum ESPRESSO input — with the reasoning behind every value.
          </Text>
        </div>
        <SimpleGrid cols={{ base: 1, sm: 3 }} spacing="md">
          {STEPS.map((step) => (
            <Group key={step.n} gap="sm" wrap="nowrap">
              <Box
                w={28}
                h={28}
                style={{
                  borderRadius: 'var(--mantine-radius-round)',
                  background: 'var(--mantine-color-gold-1)',
                  color: 'var(--mantine-color-gold-9)',
                  display: 'grid',
                  placeItems: 'center',
                  fontWeight: 700,
                  flexShrink: 0,
                }}
              >
                {step.n}
              </Box>
              <Text size="sm">{step.label}</Text>
            </Group>
          ))}
        </SimpleGrid>
      </Stack>
    </Card>
  );
}

/** The primary structure → recommended-input workflow. */
export function GuidedView() {
  const structure = useWorkspace((s) => s.structure);
  const structureStatus = useWorkspace((s) => s.structureStatus);
  const recommend = useWorkspace((s) => s.recommend);
  const records = useWorkspace((s) => s.records);
  const canRecommend = structureStatus === 'complete' && structure !== null;

  return (
    <Stack gap="lg" maw={960} mx="auto" w="100%">
      {structure === null && <GuidedWelcome />}
      <StructureSourcePanel />

      {structure !== null && (
        <>
          <SimpleGrid cols={{ base: 1, md: 2 }} spacing="md">
            <StructureSummary structure={structure} />
            <StructureViewer structure={structure} />
          </SimpleGrid>

          <OverridesPanel />

          <Group justify="flex-start">
            <Button
              onClick={() => void recommend()}
              size="md"
              rightSection={<IconArrowRight size={16} />}
              disabled={!canRecommend}
            >
              {records === null ? 'Recommend parameters' : 'Re-run recommendation'}
            </Button>
          </Group>
        </>
      )}

      <RecommendationPanel />
      <GenerationPanel />
    </Stack>
  );
}
