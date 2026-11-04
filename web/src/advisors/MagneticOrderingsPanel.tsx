import { useEffect, useState } from "react";
import {
  Badge,
  Button,
  Checkbox,
  Group,
  Stack,
  Table,
  Text,
  VisuallyHidden,
} from "@mantine/core";
import { Download, RotateCw } from "lucide-react";

import { WarningsPanel } from "../review/WarningsPanel";
import { useWorkspace, useWorkspaceSnapshot } from "../workspace/useWorkspace";
import { currentOrderings } from "../workspace/workspace";

/** What the card shows for a structure that has no listing yet. */
const UNLISTED = { result: null, operation: null, error: null } as const;

/** #87 layer 4: lists candidate magnetic orderings (FM plus any AFM
 * candidates enumerate_magnetic_orderings finds) for the currently
 * inspected structure, with an opt-in "Rank with mMACE" pass and a
 * multi-select bundle download -- see workspace.ts's
 * `magneticOrderings.*` actions for the request/response plumbing.
 * Rendered inside `MagneticOrderingsCard`, which owns the heading --
 * this component starts directly with its content. */
export function MagneticOrderingsPanel() {
  const workspace = useWorkspace();
  const snapshot = useWorkspaceSnapshot();
  const { inspection } = snapshot;
  const listing = currentOrderings(snapshot);
  const { result: magneticOrderings, operation, error } = listing ?? UNLISTED;
  const [selected, setSelected] = useState<ReadonlySet<string>>(new Set());
  // Reset the selection whenever the listed candidates change (another
  // structure, a ranking, ...), not when Download selected marks the
  // listing busy and idle again -- adjusted during render, React's own
  // recommended pattern for "reset state when an input changes", rather
  // than a second effect that would call setState after the fact.
  const [previousOrderings, setPreviousOrderings] = useState(magneticOrderings);
  if (previousOrderings !== magneticOrderings) {
    setPreviousOrderings(magneticOrderings);
    setSelected(new Set());
  }

  // Lists the open structure while it has no listing of its own. A failed
  // listing is its listing too, so its error stays and only Retry listing
  // sends it again.
  useEffect(() => {
    if (inspection !== null && listing === null) {
      void workspace.dispatch({ type: "magneticOrderings.list" });
    }
  }, [inspection, listing, workspace]);

  if (inspection === null) return null;

  const candidates = magneticOrderings?.candidates ?? [];
  const busy = operation !== null;

  function toggleSelected(label: string, checked: boolean): void {
    setSelected((current) => {
      const next = new Set(current);
      if (checked) {
        next.add(label);
      } else {
        next.delete(label);
      }
      return next;
    });
  }

  return (
    <Stack gap="sm">
      <Stack gap={4}>
        <Group justify="flex-start">
          <Button
            size="xs"
            variant="light"
            miw={160}
            loading={operation === "rank"}
            disabled={busy || candidates.length === 0}
            onClick={() =>
              void workspace.dispatch({ type: "magneticOrderings.rank" })
            }
          >
            Run mMACE
          </Button>
        </Group>
        <Text size="xs" c="dimmed">
          Relaxes each candidate ordering with mMACE (a magnetic MLIP model) and
          ranks them by energy per atom.
        </Text>
      </Stack>
      {error === null ? null : (
        <OrderingsError error={error} listed={magneticOrderings !== null} />
      )}
      <WarningsPanel warnings={magneticOrderings?.warnings ?? []} />
      {candidates.length === 0 ? (
        <Text c="dimmed" size="sm">
          {operation === "list" ? "Listing candidates…" : "No candidates yet."}
        </Text>
      ) : (
        <>
          {/* `layout="fixed"` used to force these 5 columns into
           * whatever width the card happened to have, however narrow --
           * "Ordering"/"Atoms" ran into each other and "afm-1" wrapped
           * mid-word. Natural column widths plus a scroll container let
           * every column keep its own readable width and the table
           * scroll horizontally instead, on any card width. */}
          <Table.ScrollContainer minWidth={420}>
            <Table verticalSpacing={4}>
              <Table.Caption>
                {magneticOrderings?.ranked
                  ? "Ranked by mMACE-relaxed energy per atom"
                  : "Not yet ranked"}
              </Table.Caption>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th style={{ width: "2.5rem" }}>
                    <VisuallyHidden>Select for download</VisuallyHidden>
                  </Table.Th>
                  <Table.Th>Ordering</Table.Th>
                  <Table.Th>Atoms</Table.Th>
                  <Table.Th>E/atom (eV)</Table.Th>
                  <Table.Th>Status</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {candidates.map((candidate) => (
                  <Table.Tr key={candidate.label}>
                    <Table.Td>
                      <Checkbox
                        aria-label={`Select ${candidate.label} for download`}
                        checked={selected.has(candidate.label)}
                        onChange={(event) => {
                          toggleSelected(
                            candidate.label,
                            event.currentTarget.checked,
                          );
                        }}
                      />
                    </Table.Td>
                    <Table.Td>
                      <Group gap={4} wrap="nowrap">
                        <Text size="sm">{candidate.label}</Text>
                        {candidate.is_recommended ? (
                          <Badge size="xs" color="teal">
                            Recommended
                          </Badge>
                        ) : null}
                      </Group>
                    </Table.Td>
                    <Table.Td>{candidate.natoms}</Table.Td>
                    <Table.Td>
                      {candidate.energy_per_atom_ev === null
                        ? "—"
                        : candidate.energy_per_atom_ev.toFixed(4)}
                    </Table.Td>
                    <Table.Td>{candidate.status ?? "—"}</Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
          <Group justify="flex-end">
            <Button
              size="xs"
              rightSection={<Download aria-hidden="true" size={14} />}
              loading={operation === "download"}
              disabled={busy || selected.size === 0}
              onClick={() =>
                void workspace.dispatch({
                  type: "magneticOrderings.downloadSelected",
                  labels: [...selected],
                })
              }
            >
              Download selected ({selected.size})
            </Button>
          </Group>
        </>
      )}
    </Stack>
  );
}

/** A failed listing, ranking or download of the open structure. A failed
 * listing stays the structure's listing and is not re-sent on its own
 * (#150), so it offers Retry listing; after a failed ranking or download the
 * listing is still there, and its own buttons send that request again. */
function OrderingsError({
  error,
  listed,
}: {
  readonly error: string;
  readonly listed: boolean;
}) {
  const workspace = useWorkspace();
  return (
    <Stack gap={4} align="flex-start">
      <Text c="red" size="sm" role="alert">
        {error}
      </Text>
      {listed ? null : (
        <Button
          size="xs"
          variant="light"
          leftSection={<RotateCw aria-hidden="true" size={14} />}
          onClick={() =>
            void workspace.dispatch({ type: "magneticOrderings.list" })
          }
        >
          Retry listing
        </Button>
      )}
    </Stack>
  );
}
