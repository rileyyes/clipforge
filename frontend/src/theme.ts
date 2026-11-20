// Phase 22: light / dark theme, kept in this browser.
export type Theme = "dark" | "light";
const KEY = "cf:theme";

export function getTheme(): Theme {
  try { return localStorage.getItem(KEY) === "light" ? "light" : "dark"; } catch { return "dark"; }
}
export function applyTheme(t: Theme) {
  document.documentElement.dataset.theme = t;
}
export function setTheme(t: Theme) {
  try { localStorage.setItem(KEY, t); } catch { /* storage unavailable */ }
  applyTheme(t);
  window.dispatchEvent(new CustomEvent("rjclip-theme", { detail: t }));
}
export const toggleTheme = () => setTheme(getTheme() === "light" ? "dark" : "light");
