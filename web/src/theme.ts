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
  primaryColor: "blue",
  primaryShade: 6,
  autoContrast: true,
  colors: {
    blue: [
      "#f0f7ff",
      "#dbeafe",
      "#bfdbfe",
      "#93c5fd",
      "#60a5fa",
      "#3b82f6",
      "#0071e3",
      "#005bb8",
      "#004a94",
      "#003970",
    ],
  },
  fontFamily:
    '-apple-system, BlinkMacSystemFont, Inter, "Avenir Next", "Segoe UI", ui-sans-serif, system-ui, sans-serif',
  fontFamilyMonospace: '"IBM Plex Mono", "SFMono-Regular", Consolas, monospace',
  defaultRadius: "lg",
  shadows: {
    xs: "0 1px 2px rgba(0, 0, 0, 0.04)",
    sm: "0 2px 6px rgba(0, 0, 0, 0.05)",
    md: "0 6px 16px rgba(0, 0, 0, 0.07)",
    lg: "0 16px 32px -12px rgba(0, 0, 0, 0.16)",
    xl: "0 24px 48px -16px rgba(0, 0, 0, 0.2)",
  },
  respectReducedMotion: true,
  components: {
    Button: Button.extend({
      defaultProps: { radius: "xl" },
      styles: { root: { minHeight: 44 } },
    }),
    ActionIcon: ActionIcon.extend({
      defaultProps: { size: 44, radius: "xl" },
    }),
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
