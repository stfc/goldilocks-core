import type { ReactNode } from "react";
import { type ComboboxItem, Input, NativeSelect } from "@mantine/core";

/** The select of every select-type override (boolean and enum fields, the
 * functional, the pseudopotential table). It shows the effective value
 * and, while that value is pinned, a button that resets the field to
 * automatic -- the only way back, since the options hold nothing but
 * genuine values.
 *
 * The button replaces the chevron in NativeSelect's right section, which
 * passes pointer events through to the <select> (Mantine's default
 * `rightSectionPointerEvents: "none"`) so that a click on the chevron
 * opens it. `Input.ClearButton` sets `pointer-events: all` on itself, so
 * it still receives clicks (#158) while the section keeps that default
 * for the chevron. A `style` prop on the button would replace that inline
 * style. */
export function OverrideSelect({
  label,
  description,
  disabled,
  value,
  data,
  pinned,
  onReset,
  onChange,
}: {
  readonly label: string;
  readonly description: ReactNode;
  readonly disabled: boolean;
  readonly value: string;
  readonly data: readonly ComboboxItem[];
  readonly pinned: boolean;
  readonly onReset: () => void;
  readonly onChange: (value: string) => void;
}) {
  return (
    <NativeSelect
      label={label}
      description={description}
      disabled={disabled}
      rightSection={
        pinned ? (
          <Input.ClearButton
            aria-label={`Reset ${label} to automatic`}
            disabled={disabled}
            onMouseDown={(event) => {
              // Leave focus where it is: the button unmounts on reset.
              event.preventDefault();
            }}
            onClick={() => {
              onReset();
            }}
          />
        ) : undefined
      }
      value={value}
      data={data}
      onChange={(event) => {
        onChange(event.currentTarget.value);
      }}
    />
  );
}
