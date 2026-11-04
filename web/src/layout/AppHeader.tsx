import { ActionIcon, Group, Text } from "@mantine/core";
import { Moon, Sun } from "lucide-react";

import type { Theme } from "../theme";

export function AppHeader({
  theme,
  onToggleTheme,
}: {
  readonly theme: Theme;
  readonly onToggleTheme: () => void;
}) {
  return (
    <Group
      component="header"
      justify="space-between"
      wrap="nowrap"
      px="md"
      className="app-header"
    >
      <Group gap="xs" wrap="nowrap">
        <img src="/brand/goldilocks-logo.png" alt="" width={40} height={40} />
        <Text
          style={{
            fontSize: "var(--mantine-h2-font-size)",
            fontWeight: "var(--mantine-h2-font-weight)",
            color: "#ffffff",
            lineHeight: 1.1,
          }}
        >
          Goldilocks
        </Text>
      </Group>
      <ActionIcon
        variant="subtle"
        className="app-header-toggle"
        style={{ color: "rgba(255, 255, 255, 0.85)" }}
        aria-label={
          theme === "light" ? "Switch to dark mode" : "Switch to light mode"
        }
        title={theme === "light" ? "Dark mode" : "Light mode"}
        onClick={onToggleTheme}
      >
        {theme === "light" ? (
          <Sun aria-hidden="true" size={17} />
        ) : (
          <Moon aria-hidden="true" size={17} />
        )}
      </ActionIcon>
    </Group>
  );
}
