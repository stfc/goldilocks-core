import {
  ActionIcon,
  Button,
  Checkbox,
  Input,
  NativeSelect,
  NumberInput,
  createTheme,
  localStorageColorSchemeManager,
} from "@mantine/core";

export type Theme = "light" | "dark";

export const colorSchemeManager = localStorageColorSchemeManager({
  key: "goldilocks-theme",
});

export const workbenchTheme = createTheme({
  primaryColor: "gold",
  primaryShade: 7,
  autoContrast: true,
  colors: {
    gold: [
      "#fff9e7",
      "#fff0bf",
      "#ffe38d",
      "#f8d363",
      "#e7bd52",
      "#d5a62b",
      "#b29043",
      "#94701b",
      "#745000",
      "#4f3700",
    ],
  },
  fontFamily:
    'Inter, "Avenir Next", "Segoe UI", ui-sans-serif, system-ui, sans-serif',
  fontFamilyMonospace: '"IBM Plex Mono", "SFMono-Regular", Consolas, monospace',
  defaultRadius: 0,
  respectReducedMotion: true,
  components: {
    Button: Button.extend({
      styles: { root: { minHeight: 44 } },
    }),
    ActionIcon: ActionIcon.extend({ defaultProps: { size: 44 } }),
    Input: Input.extend({ styles: { input: { minHeight: 44 } } }),
    NativeSelect: NativeSelect.extend({ defaultProps: { size: "md" } }),
    NumberInput: NumberInput.extend({
      defaultProps: { size: "md", role: "spinbutton", clampBehavior: "none" },
    }),
    Checkbox: Checkbox.extend({
      defaultProps: { size: "xs" },
      styles: { body: { minHeight: 44, alignItems: "center" } },
    }),
  },
});
