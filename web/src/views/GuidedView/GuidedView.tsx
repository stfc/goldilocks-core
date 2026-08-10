import {
  Alert,
  Badge,
  Button,
  Card,
  Collapse,
  FileInput,
  Group,
  Loader,
  Select,
  SimpleGrid,
  Stack,
  Text,
  Textarea,
  Title,
  UnstyledButton,
} from '@mantine/core';
import { IconArrowRight } from '@tabler/icons-react';
import { useState } from 'react';
import { ErrorReport } from '../../errors/ErrorReport';
import { useWorkspace } from '../../store/WorkspaceContext';
import type { StructureFormat } from '../../client/types';
import { presentRecommendation } from '../../records/presenters';
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
          <Title order={3}>Load a structure</Title>
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
      <Card withBorder radius="md">
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
          <Title order={3}>Recommendation</Title>
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
    <Card withBorder radius="md">
      <Stack gap="md">
        <Group justify="space-between" align="baseline">
          <Group gap="sm" align="baseline">
            <Title order={3}>Recommendation</Title>
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
                <Title order={5}>{section.title}</Title>
                {section.values.map((value) => (
                  <Group key={value.label} justify="space-between" gap="md">
                    <Text size="sm" c="dimmed">
                      {value.label}
                    </Text>
                    <Text size="sm" fw={600} ta="right" ff="monospace">
                      {value.value}
                      {value.unit ? ` ${value.unit}` : ''}
                    </Text>
                  </Group>
                ))}
                {section.provenance && (
                  <Text size="xs" c="dimmed">
                    {section.provenance.reason}
                  </Text>
                )}
              </Stack>
            </Card>
          ))}
        </SimpleGrid>
      </Stack>
    </Card>
  );
}

/** Minimal supported overrides; edits mark records/generated output stale. */
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
        <Stack gap="sm" mt="md" id="calculation-overrides">
          <Select
            label="Functional"
            data={['PBEsol', 'PBE', 'LDA']}
            value={intent.functional}
            onChange={(value) => value && setIntent({ functional: value })}
          />
          <Select
            label="k-point grid"
            placeholder="Let Goldilocks choose"
            data={['3 3 3', '4 4 4', '6 6 6']}
            value={hints.k_grid ? hints.k_grid.join(' ') : ''}
            onChange={(value) =>
              setHints({
                k_grid: value ? value.split(' ').map(Number) : null,
              })
            }
          />
          <Text size="xs" c="dimmed">
            Changing a value marks existing recommendations and generated inputs stale
            until you re-run the recommendation.
          </Text>
        </Stack>
      </Collapse>
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
    </Stack>
  );
}
