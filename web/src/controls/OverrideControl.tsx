import type { ReactNode } from "react";
import { useState } from "react";
import { NumberInput, Stack, Text, Textarea, TextInput } from "@mantine/core";

import type { Source } from "../api/coreClient";
import {
  automaticPlaceholder,
  describeSource,
  fieldLabel,
  type OverrideFieldMeta,
  stringifyValue,
} from "./overrideFieldMeta";
import { OverrideSelect } from "./OverrideSelect";

/** One human/heuristic override control, generic over the field's
 * declared `type` -- shared by the advisors accordion (settings) and
 * the analysis section (facts), since both are the same
 * human > ml > llm > heuristic override shape underneath.
 *
 * `resolvedValue`/`source` (boolean/enum fields only): the select shows
 * *this exact* value pre-selected -- and its own description names the
 * tier that produced it -- rather than a separate "Automatic" list entry
 * that revealed nothing about what automatic actually resolved to. A
 * human override still wins once set (`pinned`); the reset button of
 * `OverrideSelect` is the only way back to automatic now that the
 * select's own option list holds nothing but genuine values. */
export function OverrideControl({
  meta,
  value,
  resolvedValue,
  source,
  disabled,
  onChange,
}: {
  readonly meta: OverrideFieldMeta;
  readonly value: unknown;
  readonly resolvedValue?: unknown;
  readonly source?: Source | null | undefined;
  readonly disabled: boolean;
  readonly onChange: (value: unknown) => void;
}) {
  const pinned = value !== undefined;
  const label = fieldLabel(meta);
  const description = describeSource(meta.description, pinned, source);
  const effective = pinned ? value : resolvedValue;

  if (meta.type === "boolean") {
    return (
      <BooleanOverrideControl
        label={label}
        description={description}
        disabled={disabled}
        pinned={pinned}
        value={effective}
        onChange={onChange}
      />
    );
  }

  if (meta.enum && meta.enum.length > 0) {
    return (
      <EnumOverrideControl
        label={label}
        description={description}
        disabled={disabled}
        pinned={pinned}
        options={meta.enum}
        value={effective}
        onChange={onChange}
      />
    );
  }

  if (meta.type === "integer" || meta.type === "number") {
    return (
      <NumberInput
        label={label}
        description={description}
        disabled={disabled}
        placeholder={automaticPlaceholder(meta)}
        value={typeof effective === "number" ? effective : ""}
        onChange={(raw) => {
          if (raw === "") {
            onChange(undefined);
            return;
          }
          const parsed = Number(raw);
          if (Number.isFinite(parsed)) onChange(parsed);
        }}
      />
    );
  }

  if (meta.type === "string") {
    return (
      <TextInput
        label={label}
        description={description}
        disabled={disabled}
        placeholder={automaticPlaceholder(meta)}
        value={typeof effective === "string" ? effective : ""}
        onChange={(event) => {
          const raw = event.currentTarget.value;
          onChange(raw === "" ? undefined : raw);
        }}
      />
    );
  }

  return (
    <JsonOverrideControl
      label={label}
      description={meta.description}
      disabled={disabled}
      value={value}
      onChange={onChange}
    />
  );
}

function BooleanOverrideControl({
  label,
  description,
  disabled,
  pinned,
  value,
  onChange,
}: {
  readonly label: string;
  readonly description: ReactNode;
  readonly disabled: boolean;
  readonly pinned: boolean;
  readonly value: unknown;
  readonly onChange: (value: unknown) => void;
}) {
  const effectiveString =
    typeof value === "boolean" ? stringifyValue(value) : "";
  return (
    <OverrideSelect
      label={label}
      description={description}
      disabled={disabled}
      pinned={pinned}
      value={effectiveString}
      data={[
        ...(effectiveString === ""
          ? [{ value: "", label: "—", disabled: true }]
          : []),
        { value: "true", label: "On" },
        { value: "false", label: "Off" },
      ]}
      onReset={() => {
        onChange(undefined);
      }}
      onChange={(raw) => {
        onChange(raw === "true");
      }}
    />
  );
}

function EnumOverrideControl({
  label,
  description,
  disabled,
  pinned,
  options,
  value,
  onChange,
}: {
  readonly label: string;
  readonly description: ReactNode;
  readonly disabled: boolean;
  readonly pinned: boolean;
  readonly options: readonly string[];
  readonly value: unknown;
  readonly onChange: (value: unknown) => void;
}) {
  const effectiveString = typeof value === "string" ? value : "";
  const needsPlaceholder =
    effectiveString === "" || !options.includes(effectiveString);
  return (
    <OverrideSelect
      label={label}
      description={description}
      disabled={disabled}
      pinned={pinned}
      value={effectiveString}
      data={[
        ...(needsPlaceholder
          ? [{ value: "", label: "—", disabled: true }]
          : []),
        ...options.map((option) => ({ value: option, label: option })),
      ]}
      onReset={() => {
        onChange(undefined);
      }}
      onChange={onChange}
    />
  );
}

function JsonOverrideControl({
  label,
  description,
  disabled,
  value,
  onChange,
}: {
  readonly label: string;
  readonly description: string;
  readonly disabled: boolean;
  readonly value: unknown;
  readonly onChange: (value: unknown) => void;
}) {
  const [lastValue, setLastValue] = useState(value);
  const [text, setText] = useState(
    value === undefined ? "" : JSON.stringify(value),
  );
  const [error, setError] = useState<string | null>(null);
  // Resync the editable text when `value` changes for a reason other than
  // this control's own onChange (e.g. cleared elsewhere, structure
  // reopened) -- adjusting state during render, not in an effect, per
  // https://react.dev/learn/you-might-not-need-an-effect#adjusting-some-state-when-a-prop-changes.
  if (value !== lastValue) {
    setLastValue(value);
    setText(value === undefined ? "" : JSON.stringify(value));
    setError(null);
  }

  return (
    <Stack gap={4}>
      <Textarea
        label={label}
        description={`${description} (JSON)`}
        disabled={disabled}
        placeholder="Automatic"
        autosize
        minRows={1}
        value={text}
        onChange={(event) => {
          const raw = event.currentTarget.value;
          setText(raw);
          if (raw.trim() === "") {
            setError(null);
            onChange(undefined);
            return;
          }
          try {
            onChange(JSON.parse(raw) as unknown);
            setError(null);
          } catch {
            setError("Not valid JSON");
          }
        }}
      />
      {error === null ? null : (
        <Text c="red" size="xs">
          {error}
        </Text>
      )}
    </Stack>
  );
}
