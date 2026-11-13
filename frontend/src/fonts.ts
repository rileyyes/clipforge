// Phase 18: fonts (built-in + your own), text style presets, and the funny-moment / talking
// lookups. Fonts are loaded into the page once (@font-face "rjf-<id>") so the preview draws
// titles with the same font the export uses.
import { useEffect, useState } from "react";
import { ApiError, call } from "./api";
import type { TextStyle } from "./timeline/types";
import type { Moment } from "./timeline/phase18";

export interface FontInfo { id: string; family: string; category: string; source: "builtin" | "yours"; name?: string }

export const fontsApi = {
  list: () => call<{ fonts: FontInfo[] }>("GET", "/api/fonts").then((r) => r.fonts),
  add: async (f: File): Promise<FontInfo[]> => {
    const r = await fetch(`/api/fonts?filename=${encodeURIComponent(f.name)}`, { method: "POST", headers: { "X-RJClip": "1" }, body: f });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new ApiError(d.error || `Upload failed (${r.status})`, r.status, d);
    return d.fonts;
  },
  remove: (id: string) => call<{ fonts: FontInfo[] }>("DELETE", `/api/fonts/${id}`).then((r) => r.fonts),
  styles: () => call<{ styles: TextStyle[] }>("GET", "/api/text-styles").then((r) => r.styles),
  saveStyles: (styles: TextStyle[]) => call<{ styles: TextStyle[] }>("PUT", "/api/text-styles", { styles }).then((r) => r.styles),
  moments: (pid: string) => call<{ moments: Moment[] }>("GET", `/api/projects/${pid}/moments`).then((r) => r.moments),
  talk: (pid: string, mid: string) => call<{ talk: [number, number][] }>("GET", `/api/projects/${pid}/media/${mid}/talk`).then((r) => r.talk),
};

/** CSS font-family for a font id (falls back to the default title font). */
export const fontCss = (id?: string | null) => (id ? `'rjf-${id}', 'DejaVu Sans', Arial, sans-serif` : "'DejaVu Sans', Arial, sans-serif");

let cache: FontInfo[] | null = null;
let loading: Promise<FontInfo[]> | null = null;
const listeners = new Set<(f: FontInfo[]) => void>();
const injected = new Set<string>();

function inject(fonts: FontInfo[]) {
  const css = fonts.filter((f) => !injected.has(f.id)).map((f) => {
    injected.add(f.id);
    return `@font-face { font-family: 'rjf-${f.id}'; src: url('/api/fonts/${f.id}/file'); font-display: swap; }`;
  }).join("\n");
  if (!css) return;
  const el = document.createElement("style");
  el.dataset.rjFonts = "1";
  el.textContent = css;
  document.head.appendChild(el);
}

export function setFonts(fonts: FontInfo[]) {
  cache = fonts;
  inject(fonts);
  listeners.forEach((l) => l(fonts));
}

export function loadFonts(force = false): Promise<FontInfo[]> {
  if (cache && !force) return Promise.resolve(cache);
  if (!loading || force) loading = fontsApi.list().then((f) => { setFonts(f); loading = null; return f; }).catch(() => { loading = null; return cache ?? []; });
  return loading;
}

/** The font list (loads it, and the fonts themselves, the first time). */
export function useFonts(): FontInfo[] {
  const [fonts, set] = useState<FontInfo[]>(cache ?? []);
  useEffect(() => {
    listeners.add(set);
    loadFonts().then(set);
    return () => { listeners.delete(set); };
  }, []);
  return fonts;
}

/** Make sure a font is loaded before drawing with it (e.g. in a test or after an upload). */
export async function fontReady(id?: string | null): Promise<void> {
  if (!id || !document.fonts) return;
  try { await document.fonts.load(`40px 'rjf-${id}'`); } catch { /* the default font then */ }
}
