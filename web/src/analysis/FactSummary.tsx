import { useId } from "react";
import { Input, Text } from "@mantine/core";

import type { Fact, ResolvedField } from "../api/coreClient";
import {
  describeSource,
  fieldLabel,
  stringifyValue,
} from "../controls/overrideFieldMeta";

/** A fact that takes no override (`Fact.overridable` false, such as
 * `needs_soc`, #186), shown read-only: the label and description of an
 * override control, at the size of the selects beside it (the theme's
 * NativeSelect size), the description naming the tier that resolved the
 * value, then the value itself as text ("—" until one resolves). A group
 * named by the label and described by the description holds the three. */
export function FactSummary({
  fact,
  record,
}: {
  readonly fact: Fact;
  readonly record: ResolvedField | undefined;
}) {
  const labelId = useId();
  const descriptionId = useId();
  const resolved = record?.status === "resolved" ? record : undefined;
  return (
    <Input.Wrapper
      size="md"
      role="group"
      aria-labelledby={labelId}
      aria-describedby={descriptionId}
      labelElement="div"
      label={fieldLabel({ key: fact.key, unit: null })}
      labelProps={{ id: labelId }}
      description={describeSource(fact.description, false, resolved?.source)}
      descriptionProps={{ id: descriptionId }}
    >
      <Text size="md">{factValueText(resolved?.value)}</Text>
    </Input.Wrapper>
  );
}

/** A boolean as Yes/No, as `ScientificRecord` shows one; "—" for none. */
function factValueText(value: unknown): string {
  if (value === undefined || value === null) return "—";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  return stringifyValue(value);
}
