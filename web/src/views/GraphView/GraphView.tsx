import {
  Badge,
  Box,
  Button,
  Card,
  Checkbox,
  Group,
  Loader,
  SimpleGrid,
  Stack,
  Text,
  Title,
} from '@mantine/core';
import { useMediaQuery } from '@mantine/hooks';
import { IconPlayerPlay, IconCheck, IconLink } from '@tabler/icons-react';
import {
  Background,
  Controls,
  MiniMap,
  ReactFlow,
  ReactFlowProvider,
  useEdgesState,
  useNodesState,
  type Edge,
  type Node,
  type NodeProps,
} from '@xyflow/react';
import { Component, useEffect, useMemo, type ReactNode } from 'react';
import type { RecordName, TaskCatalogue } from '../../client/types';
import { ErrorReport } from '../../errors/ErrorReport';
import { RawRecord } from '../../records/RawRecord';
import { presentRecordSet } from '../../records/presenters';
import { useWorkspace } from '../../store/WorkspaceContext';
import {
  buildGraphPresentation,
  type GraphEdge,
  type GraphNode,
  type GraphNodeKind,
} from './graphModel';

/**
 * Contains a rendering failure (e.g. the canvas library) within Graph view.
 * The Guided view is a separate mount in the shell, so a crash here never
 * disables it. Retrying remounts the canvas without discarding workspace state.
 */
class CanvasBoundary extends Component<
  { children: ReactNode },
  { error: Error | null; attempt: number }
> {
  state = { error: null as Error | null, attempt: 0 };

  static getDerivedStateFromError(error: Error) {
    return { error, attempt: 0 };
  }

  render() {
    if (this.state.error !== null) {
      return (
        <Box style={{ height: 520 }}>
          <Card withBorder radius="md">
            <Stack gap="sm">
              <Title order={3}>Graph canvas unavailable</Title>
              <Text size="sm">
                The graph could not be rendered. Your structure, selection, and results
                remain intact; Guided view is unaffected.
              </Text>
              <Box>
                <Button
                  variant="light"
                  onClick={() =>
                    this.setState((s) => ({ error: null, attempt: s.attempt + 1 }))
                  }
                >
                  Retry canvas
                </Button>
              </Box>
            </Stack>
          </Card>
        </Box>
      );
    }
    return <div key={this.state.attempt}>{this.props.children}</div>;
  }
}

const nodeTypes = { record: RecordNode };

type FlowNode = Node<{ label: string; description: string; kind: string }>;
type FlowEdge = Edge;

function toFlowNodes(graphNodes: GraphNode[]): FlowNode[] {
  return graphNodes.map((node) => ({
    id: node.id,
    type: 'record',
    position: { x: node.x, y: node.y },
    data: {
      label: node.name,
      description: node.description,
      kind: node.kind,
    },
  }));
}

function toFlowEdges(graphEdges: GraphEdge[]): FlowEdge[] {
  return graphEdges.map((edge) => ({
    id: edge.id,
    source: edge.source,
    target: edge.target,
    animated: false,
  }));
}

function RecordNode({ data }: NodeProps<FlowNode>) {
  const border =
    data.kind === 'selected'
      ? '2px solid var(--mantine-color-gold-6)'
      : data.kind === 'required'
        ? '2px solid var(--mantine-color-ink-4)'
        : '1px solid var(--mantine-color-stone-3)';
  // Selection/requirement is never conveyed by colour alone: each node carries
  // a text + icon cue so screen readers and colour-blind users can tell
  // selected, required-dependency, and unused stages apart.
  const kindCue =
    data.kind === 'selected' ? (
      <Group gap={5} wrap="nowrap">
        <IconCheck size={12} aria-hidden="true" />
        <Text size="xs" fw={700} c="gold">
          Selected output
        </Text>
      </Group>
    ) : data.kind === 'required' ? (
      <Group gap={5} wrap="nowrap">
        <IconLink size={12} aria-hidden="true" />
        <Text size="xs" fw={600} c="dimmed">
          Required dependency
        </Text>
      </Group>
    ) : null;
  return (
    <Box
      style={{
        border,
        borderRadius: 'var(--mantine-radius-md)',
        background: 'var(--mantine-color-stone-0)',
        padding: '10px 14px',
        width: 180,
        boxShadow: 'var(--mantine-shadow-xs)',
        opacity: data.kind === 'unused' ? 0.72 : 1,
      }}
    >
      {kindCue}
      <Text size="sm" fw={600} lineClamp={1}>
        {data.label}
      </Text>
      <Text size="xs" c="dimmed" lineClamp={2}>
        {data.description}
      </Text>
    </Box>
  );
}

function GraphCanvas({ catalogue }: { catalogue: TaskCatalogue }) {
  const task = catalogue.tasks[0];
  const selectedIds = useWorkspace((s) => s.selectedRecordIds);
  const presentation = useMemo(
    () => buildGraphPresentation(task, selectedIds),
    [task, selectedIds],
  );

  const nodes = useMemo(() => toFlowNodes(presentation.nodes), [presentation]);
  const edges = useMemo(() => toFlowEdges(presentation.edges), [presentation]);

  return (
    <Box
      style={{
        height: 520,
        border: '1px solid var(--mantine-color-stone-3)',
        borderRadius: 'var(--mantine-radius-md)',
        overflow: 'hidden',
      }}
    >
      {/* Remount on node-count change so fitView re-runs after the catalogue loads. */}
      <ReactFlowProvider>
        <CanvasInner key={nodes.length} nodes={nodes} edges={edges} />
      </ReactFlowProvider>
    </Box>
  );
}

const KIND_ORDER: GraphNodeKind[] = ['selected', 'required', 'unused'];
const KIND_TITLE: Record<GraphNodeKind, string> = {
  selected: 'Selected output records',
  required: 'Required dependency stages',
  unused: 'Available stages',
};

/** Readable narrow-screen fallback for the Graph canvas.
 *
 * On small widths the pan/zoom canvas is cramped, so we render the same
 * backend-owned topology as an accessible, grouped list instead. Selection
 * still flows through the store, so toggles and execution behave identically;
 * only the presentation medium changes. Never a broken canvas. */
function StageListFallback({ catalogue }: { catalogue: TaskCatalogue }) {
  const task = catalogue.tasks[0];
  const selectedIds = useWorkspace((s) => s.selectedRecordIds);
  const presentation = useMemo(
    () => buildGraphPresentation(task, selectedIds),
    [task, selectedIds],
  );
  const byOutput = useMemo(
    () => new Map(task.stages.map((stage) => [stage.output_record_id, stage])),
    [task],
  );

  const grouped = KIND_ORDER.map((kind) => ({
    kind,
    nodes: presentation.nodes
      .filter((node) => node.kind === kind)
      .sort((a, b) => a.name.localeCompare(b.name)),
  })).filter((group) => group.nodes.length > 0);

  return (
    <Box
      style={{
        border: '1px solid var(--mantine-color-stone-3)',
        borderRadius: 'var(--mantine-radius-md)',
        overflow: 'hidden',
      }}
      role="list"
      aria-label="Task graph stages"
    >
      <Stack gap="md" p="md">
        {grouped.map((group) => (
          <Box key={group.kind}>
            <Text size="xs" fw={700} tt="uppercase" c="dimmed" mb={6}>
              {KIND_TITLE[group.kind]}
            </Text>
            <Stack gap={4}>
              {group.nodes.map((node) => {
                const stage = byOutput.get(node.id);
                const inputs = stage?.input_record_ids ?? [];
                return (
                  <Group
                    key={node.id}
                    role="listitem"
                    gap="sm"
                    align="flex-start"
                    wrap="nowrap"
                  >
                    {node.kind === 'selected' ? (
                      <IconCheck size={15} aria-hidden="true" />
                    ) : node.kind === 'required' ? (
                      <IconLink size={15} aria-hidden="true" />
                    ) : (
                      <Box w={15} h={15} />
                    )}
                    <Box>
                      <Text size="sm" fw={600}>
                        {node.name}
                      </Text>
                      {inputs.length > 0 && (
                        <Text size="xs" c="dimmed">
                          depends on {inputs.join(', ')}
                        </Text>
                      )}
                    </Box>
                  </Group>
                );
              })}
            </Stack>
          </Box>
        ))}
      </Stack>
    </Box>
  );
}

function CanvasInner({ nodes, edges }: { nodes: FlowNode[]; edges: FlowEdge[] }) {
  const [rfNodes, setNodes, onNodesChange] = useNodesState(nodes);
  const [rfEdges, setEdges, onEdgesChange] = useEdgesState(edges);

  useEffect(() => {
    setNodes(nodes);
    setEdges(edges);
  }, [nodes, edges, setNodes, setEdges]);

  return (
    <ReactFlow
      nodes={rfNodes}
      edges={rfEdges}
      onNodesChange={onNodesChange}
      onEdgesChange={onEdgesChange}
      nodeTypes={nodeTypes}
      nodesConnectable={false}
      edgesReconnectable={false}
      deleteKeyCode={null}
      elementsSelectable
      nodesDraggable
      fitView
      fitViewOptions={{ padding: 0.2 }}
      minZoom={0.2}
      maxZoom={2}
      proOptions={{ hideAttribution: true }}
    >
      <Background />
      <Controls showInteractive={false} />
      <MiniMap pannable zoomable />
    </ReactFlow>
  );
}

function recordName(task: TaskCatalogue, id: string): string {
  const stage = task.tasks[0].stages.find((s) => s.output_record_id === id);
  return stage?.name ?? id;
}

/** Keyboard-accessible record selection toggles plus the run action. */
function SelectionPanel({ catalogue }: { catalogue: TaskCatalogue }) {
  const task = catalogue.tasks[0];
  const selectedRecordIds = useWorkspace((s) => s.selectedRecordIds);
  const setSelectedRecords = useWorkspace((s) => s.setSelectedRecords);
  const runSelectedRecords = useWorkspace((s) => s.runSelectedRecords);
  const graphStatus = useWorkspace((s) => s.graphStatus);
  const structure = useWorkspace((s) => s.structure);

  const toggle = (id: RecordName) => {
    setSelectedRecords(
      selectedRecordIds.includes(id)
        ? selectedRecordIds.filter((r) => r !== id)
        : [...selectedRecordIds, id],
    );
  };

  const running = graphStatus === 'running';
  const canRun = structure !== null && selectedRecordIds.length > 0 && !running;

  return (
    <Card withBorder radius="md">
      <Stack gap="md">
        <div>
          <Title order={3}>Selected records</Title>
          <Text size="xs" c="dimmed">
            Choose the output records to compute. Required dependency stages are pulled
            in automatically; they are shown on the graph and are never editable.
          </Text>
        </div>

        <Stack gap={4}>
          {task.selectable_record_ids.map((id) => (
            <Checkbox
              key={id}
              label={recordName(catalogue, id)}
              checked={selectedRecordIds.includes(id as RecordName)}
              onChange={() => toggle(id as RecordName)}
              aria-label={`Compute record ${recordName(catalogue, id)}`}
            />
          ))}
        </Stack>

        {structure === null && (
          <Text size="xs" c="dimmed">
            Load a structure first (in Guided view) to run selected records.
          </Text>
        )}

        <Button
          onClick={() => void runSelectedRecords()}
          leftSection={<IconPlayerPlay size={16} />}
          loading={running}
          loaderProps={{ type: 'dots' }}
          disabled={!canRun}
        >
          Run selected records
        </Button>
      </Stack>
    </Card>
  );
}

/** Presented values and raw disclosure for the executed records. */
function GraphResults() {
  const graphRecords = useWorkspace((s) => s.graphRecords);
  const graphStatus = useWorkspace((s) => s.graphStatus);
  const graphFailure = useWorkspace((s) => s.graphFailure);
  const graphStale = useWorkspace((s) => s.graphStale);

  if (graphStatus === 'running' && graphRecords === null) {
    return (
      <Card withBorder radius="md" role="status">
        <Group justify="center" gap="sm" py="lg">
          <Loader size="sm" />
          <Text size="sm" c="dimmed">
            Running selected records…
          </Text>
        </Group>
      </Card>
    );
  }

  if (graphStatus === 'failed' && graphRecords === null) {
    return (
      <Card withBorder radius="md">
        <Stack gap="sm">
          <Title order={2}>Record results</Title>
          {graphFailure !== null && <ErrorReport failure={graphFailure} />}
          <Text size="sm" c="dimmed">
            The selected records did not complete. Your structure, Guided
            recommendation, and prior results remain available — adjust the selection
            and retry.
          </Text>
        </Stack>
      </Card>
    );
  }

  if (graphRecords === null) {
    return null;
  }

  const sections = presentRecordSet(graphRecords);

  return (
    <Card withBorder radius="md">
      <Stack gap="md">
        <Group justify="space-between" align="baseline">
          <Group gap="sm" align="baseline">
            <Title order={2}>Record results</Title>
            {graphStale && (
              <Badge variant="light" color="ink">
                Stale
              </Badge>
            )}
          </Group>
        </Group>

        {sections.length === 0 ? (
          <Text size="sm" c="dimmed">
            No records returned for the current selection.
          </Text>
        ) : (
          <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="md">
            {sections.map((section) => (
              <Card
                key={section.id}
                withBorder
                radius="md"
                bg="var(--mantine-color-stone-0)"
              >
                <Stack gap="xs">
                  <Title order={3}>{section.title}</Title>
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
        )}

        <RawRecord data={graphRecords} label="Raw records" id="graph-results" />
      </Stack>
    </Card>
  );
}

/** Backend-driven Graph view: inspect immutable topology and execute records. */
export function GraphView() {
  const catalogue = useWorkspace((s) => s.catalogue);
  const catalogueStatus = useWorkspace((s) => s.catalogueStatus);
  const catalogueFailure = useWorkspace((s) => s.catalogueFailure);
  const loadTaskCatalogue = useWorkspace((s) => s.loadTaskCatalogue);
  // Below ~768px the pan/zoom canvas is too cramped; swap it for the readable
  // grouped stage list (same topology, same store), so Graph never degrades
  // into a broken canvas.
  const isNarrow = useMediaQuery('(max-width: 767px)');

  useEffect(() => {
    if (catalogueStatus === 'idle') void loadTaskCatalogue();
  }, [catalogueStatus, loadTaskCatalogue]);

  return (
    <Stack gap="lg" maw={1200} mx="auto" w="100%">
      <Card withBorder radius="md">
        <Title order={2}>Task Graph</Title>
        {catalogue?.tasks[0] && (
          <Text size="sm" c="dimmed">
            {catalogue.tasks[0].name} — {catalogue.tasks[0].description}
          </Text>
        )}
        <Group gap="lg" mt="sm">
          <Group gap={6}>
            <Badge variant="light" color="gold">
              Selected output
            </Badge>
            <Badge variant="light" color="ink">
              Required dependency
            </Badge>
            <Badge variant="light" color="stone">
              Available stage
            </Badge>
          </Group>
          <Text size="xs" c="dimmed">
            Topology is backend-owned and immutable. You may pan, zoom, fit, select, and
            reposition nodes; adding, deleting, or reconnecting them is disabled.
          </Text>
        </Group>
      </Card>

      {catalogueStatus === 'failed' && catalogue === null && (
        <Card withBorder radius="md">
          <Stack gap="sm">
            <Title order={2}>Task graph unavailable</Title>
            {catalogueFailure !== null && <ErrorReport failure={catalogueFailure} />}
            <Text size="sm" c="dimmed">
              The task topology could not be loaded. Guided view is unaffected.
            </Text>
            <Box>
              <Button onClick={() => void loadTaskCatalogue()} variant="light">
                Retry
              </Button>
            </Box>
          </Stack>
        </Card>
      )}

      {catalogueStatus === 'running' && catalogue === null && (
        <Card withBorder radius="md" role="status">
          <Group justify="center" gap="sm" py="lg">
            <Loader size="sm" />
            <Text size="sm" c="dimmed">
              Loading task topology…
            </Text>
          </Group>
        </Card>
      )}

      {catalogue !== null && (
        <>
          {catalogue.tasks.length === 0 ? (
            <Card withBorder radius="md">
              <Text size="sm" c="dimmed">
                No Core tasks are registered on this server.
              </Text>
            </Card>
          ) : (
            <SimpleGrid cols={{ base: 1, lg: 3 }} spacing="md">
              <Box style={{ gridColumn: 'span 2' }}>
                {isNarrow ? (
                  <StageListFallback catalogue={catalogue} />
                ) : (
                  <CanvasBoundary>
                    <GraphCanvas catalogue={catalogue} />
                  </CanvasBoundary>
                )}
              </Box>
              <SelectionPanel catalogue={catalogue} />
            </SimpleGrid>
          )}

          <GraphResults />
        </>
      )}
    </Stack>
  );
}
