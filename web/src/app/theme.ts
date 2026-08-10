import { createTheme, rem, type MantineColorsTuple } from '@mantine/core';

// Warm gold primary over restrained ink/stone neutrals. Scientific values are
// rendered in high-contrast ink on a near-white stone background. Status is
// never encoded by colour alone elsewhere in the app; colour here only sets
// the deliberate visual identity.

const gold: MantineColorsTuple = [
  '#fdf6e7',
  '#f9ecc9',
  '#f4dc9a',
  '#eec96a',
  '#e8b741',
  '#e0a427',
  '#d18c17',
  '#ab7010',
  '#8a5a0d',
  '#68450a',
];

const ink: MantineColorsTuple = [
  '#f5f6f8',
  '#e6e8ec',
  '#ccd1d9',
  '#a9b0bd',
  '#7f8896',
  '#5d6672',
  '#454c57',
  '#333841',
  '#23262d',
  '#17191d',
];

const stone: MantineColorsTuple = [
  '#faf8f5',
  '#f1eee9',
  '#e2dcd3',
  '#cfc6b8',
  '#b8ab97',
  '#a0917a',
  '#7d7059',
  '#5f5444',
  '#4a4134',
  '#332d25',
];

export const theme = createTheme({
  // Dark ink primary: filled interactive controls carry high-contrast white
  // text. Warm gold is reserved as the accent (brand, badges, highlights,
  // focus rings) rather than used as a fill, because white text fails WCAG AA
  // on every warm gold shade.
  primaryColor: 'ink',
  colors: {
    gold,
    ink,
    stone,
  },
  defaultRadius: 'md',
  fontFamily:
    "system-ui, -apple-system, 'Segoe UI', Roboto, 'Helvetica Neue', sans-serif",
  fontFamilyMonospace:
    "ui-monospace, 'SFMono-Regular', 'JetBrains Mono', Menlo, Consolas, monospace",
  headings: {
    fontFamily:
      "'Iowan Old Style', 'Palatino Linotype', 'Book Antiqua', Palatino, Georgia, serif",
    fontWeight: '600',
  },
  spacing: {
    xs: rem(6),
    sm: rem(10),
    md: rem(16),
    lg: rem(24),
    xl: rem(36),
  },
  components: {
    Card: {
      defaultProps: {
        padding: 'lg',
        radius: 'md',
      },
    },
  },
});
