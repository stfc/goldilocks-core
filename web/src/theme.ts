import {
  Button,
  Checkbox,
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
      styles: {
        root: { height: "var(--target-size)" },
        inner: { gap: "var(--space-2)" },
        label: { fontWeight: "inherit" },
        section: { margin: 0 },
      },
    }),
    NumberInput: NumberInput.extend({
      defaultProps: { role: "spinbutton", clampBehavior: "none" },
    }),
    Checkbox: Checkbox.extend({
      defaultProps: { size: "md" },
    }),
  },
});
