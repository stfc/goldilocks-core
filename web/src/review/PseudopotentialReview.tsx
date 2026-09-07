import {
  Accordion,
  Badge,
  Code,
  Group,
  Paper,
  Stack,
  Text,
  Title,
} from "@mantine/core";

import type { ComputationResult } from "../api/coreClient";
import { artifactDigest } from "./artifacts";

export function PseudopotentialReview({
  result,
}: {
  readonly result: ComputationResult;
}) {
  const inputData = result.records.dft_input_data;
  const selection = result.records.selection;
  if (inputData === undefined || selection === undefined) return null;
  const table = inputData.pseudopotential_set;
  return (
    <Stack component="section" gap="sm" miw={0}>
      <header>
        <Title order={3}>Pseudopotentials</Title>
        <Text size="sm" c="dimmed">
          {table.provider} · {table.version ?? "unversioned"}
        </Text>
      </header>
      <Paper withBorder p="sm">
        <Group justify="space-between">
          <Text size="sm">
            {table.functional} · {table.accuracy}
          </Text>
          <Code aria-label="Pseudopotential set">{table.id}</Code>
        </Group>
      </Paper>
      <Stack component="ul" gap="sm" m={0} p={0} style={{ listStyle: "none" }}>
        {selection.pseudopotentials.map((item) => {
          const digest = artifactDigest(inputData.artifacts, item.filename);
          return (
            <Group component="li" key={item.element} wrap="nowrap" gap="sm">
              <Badge>{item.element}</Badge>
              <Stack
                gap={0}
                miw={0}
                flex={1}
                style={{ overflowWrap: "anywhere" }}
              >
                <Text size="sm">{item.filename ?? "Filename unavailable"}</Text>
                <Text size="xs" c="dimmed">
                  {item.relativistic ?? "unknown"} · {item.ecutwfc_ry ?? "—"} /{" "}
                  {item.ecutrho_ry ?? "—"} Ry
                </Text>
              </Stack>
              {digest === null ? null : (
                <Code title={digest}>{digest.slice(0, 8)}</Code>
              )}
            </Group>
          );
        })}
      </Stack>
      <Group justify="space-between">
        <Text size="sm" c="dimmed">
          Licence
        </Text>
        <Text size="sm">{table.licence}</Text>
      </Group>
      <Accordion order={4}>
        <Accordion.Item value="citation">
          <Accordion.Control>Citation and provenance</Accordion.Control>
          <Accordion.Panel>{table.citation}</Accordion.Panel>
        </Accordion.Item>
      </Accordion>
    </Stack>
  );
}
