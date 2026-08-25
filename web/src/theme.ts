import { useState } from "react";

export type Theme = "light" | "dark";

const STORAGE_KEY = "goldilocks-theme";
const THEME_COLORS: Readonly<Record<Theme, string>> = {
  light: "#f0eee8",
  dark: "#10171b",
};

export function useTheme(): {
  readonly theme: Theme;
  readonly toggleTheme: () => void;
} {
  const [theme, setTheme] = useState<Theme>(() => {
    const initial = storedTheme();
    applyTheme(initial);
    return initial;
  });

  return {
    theme,
    toggleTheme: () => {
      setTheme((current) => {
        const next = current === "light" ? "dark" : "light";
        window.localStorage.setItem(STORAGE_KEY, next);
        applyTheme(next);
        return next;
      });
    },
  };
}

function storedTheme(): Theme {
  return window.localStorage.getItem(STORAGE_KEY) === "dark" ? "dark" : "light";
}

function applyTheme(theme: Theme): void {
  document.documentElement.dataset.theme = theme;
  document.documentElement.style.colorScheme = theme;
  document
    .querySelector<HTMLMetaElement>('meta[name="theme-color"]')
    ?.setAttribute("content", THEME_COLORS[theme]);
}
