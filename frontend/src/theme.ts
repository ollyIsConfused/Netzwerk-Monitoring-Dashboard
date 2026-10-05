import { useEffect, useState } from "react";

export type Theme = "light" | "dark";

function storedTheme(): Theme | null {
  try {
    const value = localStorage.getItem("theme");
    return value === "light" || value === "dark" ? value : null;
  } catch {
    return null;
  }
}

function systemTheme(): Theme {
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

/** Hell/Dunkel: folgt dem System, bis man selbst umschaltet (Wahl wird gemerkt). */
export function useTheme(): [Theme, () => void] {
  const [theme, setTheme] = useState<Theme>(() => storedTheme() ?? systemTheme());

  useEffect(() => {
    if (storedTheme()) document.documentElement.dataset.theme = theme;
  }, [theme]);

  function toggle() {
    const next: Theme = theme === "dark" ? "light" : "dark";
    try {
      localStorage.setItem("theme", next);
    } catch {
      // ohne Speicher gilt die Wahl nur bis zum Neuladen
    }
    document.documentElement.dataset.theme = next;
    setTheme(next);
  }

  return [theme, toggle];
}
