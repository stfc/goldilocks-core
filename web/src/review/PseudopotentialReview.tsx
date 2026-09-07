import { Accordion, Box, Center, Group, Text } from "@mantine/core";

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
    <section className="review-section pseudo-review">
      <Group component="header" gap={12} wrap="nowrap" mb={16}>
        <span className="review-section__index">C</span>
        <div>
          <h3>Pseudopotentials</h3>
          <p>
            {table.provider} · {table.version ?? "unversioned"}
          </p>
        </div>
      </Group>
      <Group
        className="pseudo-table-id"
        justify="space-between"
        wrap="nowrap"
        gap={12}
        p={12}
      >
        <span>
          {table.functional} · {table.accuracy}
        </span>
        <code>{table.id}</code>
      </Group>
      <ul className="pseudo-files">
        {selection.pseudopotentials.map((item) => {
          const digest = artifactDigest(inputData.artifacts, item.filename);
          return (
            <li key={item.element}>
              <Center component="span" className="element-badge" w={32} h={32}>
                {item.element}
              </Center>
              <Box miw={0}>
                <Text
                  component="strong"
                  inherit
                  truncate
                  fw={500}
                  display="block"
                >
                  {item.filename ?? "Filename unavailable"}
                </Text>
                <Text
                  component="span"
                  inherit
                  truncate
                  c="var(--color-text-muted)"
                  mt={4}
                  display="block"
                >
                  {item.relativistic ?? "unknown"} · {item.ecutwfc_ry ?? "—"} /{" "}
                  {item.ecutrho_ry ?? "—"} Ry
                </Text>
              </Box>
              {digest === null ? null : (
                <code title={digest}>{digest.slice(0, 8)}</code>
              )}
            </li>
          );
        })}
      </ul>
      <Group
        component="p"
        justify="space-between"
        align="stretch"
        wrap="nowrap"
        gap={12}
        mt={12}
        mb={0}
        c="var(--color-text-secondary)"
        fz="var(--text-xs)"
      >
        <span>Licence</span>
        <Text component="strong" inherit c="var(--color-text)" fw={550}>
          {table.licence}
        </Text>
      </Group>
      <Accordion
        order={4}
        chevron={<span aria-hidden="true" />}
        disableChevronRotation
        className="review-disclosure citation"
      >
        <Accordion.Item value="citation">
          <Accordion.Control>Citation and provenance</Accordion.Control>
          <Accordion.Panel>
            <p>{table.citation}</p>
          </Accordion.Panel>
        </Accordion.Item>
      </Accordion>
    </section>
  );
}
