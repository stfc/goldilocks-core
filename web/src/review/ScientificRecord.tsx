import type { ReactNode } from "react";
import { Badge, Paper, Stack, Table, Text } from "@mantine/core";

import type { ResolvedField, Source } from "../api/coreClient";
import { SourceLabel } from "../api/SourceLabel";
import { isAdvisorWarning } from "./warnings";

/** Renders one `ResolvedField` generically -- v2's `records()` docstring
 * is explicit that there is no codified schema for a record's `value`
 * shape beyond the tri-state envelope itself ("No such key set is
 * codified anywhere else in the codebase"), so a per-record hand-coded
 * presenter (v1's approach) would just be the next contract drift
 * waiting to happen. This walks whatever value/object/array shape an
 * advisor actually returned. */
export function ScientificRecord({ field }: { readonly field: ResolvedField }) {
  if (field.status === "unavailable") {
    return (
      <Text size="sm" c="dimmed">
        Unavailable -- {field.reason ?? "no reason given"}
      </Text>
    );
  }
  if (field.status === "blocked") {
    return (
      <Text size="sm" c="red">
        Blocked -- {field.blocked_by ?? "an upstream field failed"}
      </Text>
    );
  }
  return (
    <Stack gap="xs">
      <Badge color="gray" variant="light" style={{ alignSelf: "flex-start" }}>
        <SourceLabel source={field.source ?? "heuristic"} />
      </Badge>
      <RecordValue value={field.value} />
      {field.field_sources === undefined ||
      field.field_sources === null ? null : (
        <FieldSources sources={field.field_sources} />
      )}
    </Stack>
  );
}

function FieldSources({
  sources,
}: {
  readonly sources: Readonly<Record<string, Source>>;
}) {
  const entries = Object.entries(sources);
  if (entries.length === 0) return null;
  return (
    <Table layout="fixed" verticalSpacing={4}>
      <Table.Caption>Per-field sources</Table.Caption>
      <Table.Tbody>
        {entries.map(([key, source]) => (
          <Table.Tr key={key}>
            <Table.Th scope="row">{humanizeKey(key)}</Table.Th>
            <Table.Td>
              <SourceLabel source={source} />
            </Table.Td>
          </Table.Tr>
        ))}
      </Table.Tbody>
    </Table>
  );
}

function RecordValue({ value }: { readonly value: unknown }): ReactNode {
  if (value === null || value === undefined) {
    return (
      <Text size="sm" c="dimmed">
        None
      </Text>
    );
  }
  if (typeof value === "boolean") {
    return <Text size="sm">{value ? "Yes" : "No"}</Text>;
  }
  if (typeof value === "number" || typeof value === "string") {
    return <Text size="sm">{String(value)}</Text>;
  }
  if (Array.isArray(value)) {
    // `Array.isArray` narrows to `any[]` (a lib.es5.d.ts quirk), not
    // `unknown[]` -- rebind through an explicit `unknown[]` so `any`
    // doesn't leak into the recursive calls below.
    const items: unknown[] = value;
    if (items.length === 0) {
      return (
        <Text size="sm" c="dimmed">
          Empty
        </Text>
      );
    }
    if (items.every((item) => item === null || typeof item !== "object")) {
      return <Text size="sm">{items.map(String).join(", ")}</Text>;
    }
    return (
      <Stack gap="xs">
        {items.map((item, index) => (
          <Paper key={index} withBorder p="xs">
            <RecordValue value={item} />
          </Paper>
        ))}
      </Stack>
    );
  }
  const entries = Object.entries(value as Readonly<Record<string, unknown>>);
  const warnings = entries.find(([key]) => key === "warnings")?.[1];
  const rest = entries.filter(([key]) => key !== "warnings");
  if (rest.length === 0 && !Array.isArray(warnings)) {
    return (
      <Text size="sm" c="dimmed">
        None
      </Text>
    );
  }
  return (
    <Stack gap="xs">
      {rest.length === 0 ? null : (
        <Table
          layout="fixed"
          verticalSpacing={4}
          style={{ overflowWrap: "anywhere" }}
        >
          <Table.Tbody>
            {rest.map(([key, item]) => (
              <Table.Tr key={key}>
                <Table.Th scope="row">{humanizeKey(key)}</Table.Th>
                <Table.Td>
                  <RecordValue value={item} />
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      )}
      <RecordWarnings warnings={warnings} />
    </Stack>
  );
}

function RecordWarnings({ warnings }: { readonly warnings: unknown }) {
  if (!Array.isArray(warnings) || warnings.length === 0) return null;
  return (
    <Stack component="ul" gap={4} m={0} pl="md">
      {warnings.map((warning, index) => (
        <Text component="li" key={index} size="sm">
          {isAdvisorWarning(warning) ? warning.message : String(warning)}
        </Text>
      ))}
    </Stack>
  );
}

function humanizeKey(value: string): string {
  return value
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}
