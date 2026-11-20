// Phase 22: the editor's panel sizes (media bin, tool panel, timeline) — dragged by the user,
// kept between sessions in this browser, and always squeezed to fit the window.

export interface Layout { left: number; right: number; timeline: number; mediaOpen: boolean }

export const NAV = 56;                 // the app's left icon bar
export const TOP = 46;                 // the editor's top bar
export const COLLAPSED = 30;           // the media bin when folded away
export const MIN_LEFT = 160, MAX_LEFT = 480;
export const MIN_RIGHT = 260, MAX_RIGHT = 720;
export const MIN_PREVIEW_W = 320, MIN_PREVIEW_H = 220;
export const MIN_TL = 140;
const KEY = "cf:layout";

/** What the editor used before panels could be resized (same breakpoints). */
export function defaultLayout(w: number, h: number): Layout {
  const left = w <= 1300 ? 190 : w <= 1440 ? 220 : 280;
  const right = w <= 1300 ? 280 : 290;
  return fit({ left, right, timeline: Math.round(h * 0.38), mediaOpen: true }, w, h);
}

/** Keep every part usable in a w×h window: the preview at least MIN_PREVIEW_W wide and
 *  MIN_PREVIEW_H tall; the side panels shrink (the tool panel last) before it does. */
export function fit(l: Layout, w: number, h: number): Layout {
  const num = (v: number, d: number) => (Number.isFinite(v) ? v : d);
  let left = Math.round(Math.max(MIN_LEFT, Math.min(MAX_LEFT, num(l.left, 220))));
  let right = Math.round(Math.max(MIN_RIGHT, Math.min(MAX_RIGHT, num(l.right, 290))));
  const room = w - NAV - MIN_PREVIEW_W - (l.mediaOpen ? 0 : COLLAPSED);
  if (l.mediaOpen) {
    const over = left + right - room;
    if (over > 0) left = Math.max(MIN_LEFT, left - over);
    const over2 = left + right - room;
    if (over2 > 0) right = Math.max(MIN_RIGHT, right - over2);
  } else if (right > room) right = Math.max(MIN_RIGHT, room);
  const tlMax = Math.max(MIN_TL, h - TOP - 6 - MIN_PREVIEW_H);
  const timeline = Math.round(Math.max(MIN_TL, Math.min(tlMax, num(l.timeline, h * 0.38))));
  return { left, right, timeline, mediaOpen: l.mediaOpen !== false };
}

/** Grid columns for the middle row. */
export function columns(l: Layout): string {
  return `${l.mediaOpen ? l.left : COLLAPSED}px minmax(0, 1fr) ${l.right}px`;
}

export function loadLayout(w: number, h: number): Layout {
  try {
    const raw = localStorage.getItem(KEY);
    if (raw) {
      const v = JSON.parse(raw);
      if (v && typeof v === "object") return fit({ ...defaultLayout(w, h), ...pick(v) }, w, h);
    }
  } catch { /* storage unavailable or broken: defaults */ }
  return defaultLayout(w, h);
}

function pick(v: any): Partial<Layout> {
  const out: Partial<Layout> = {};
  for (const k of ["left", "right", "timeline"] as const) if (typeof v[k] === "number") out[k] = v[k];
  if (typeof v.mediaOpen === "boolean") out.mediaOpen = v.mediaOpen;
  return out;
}

export function saveLayout(l: Layout) {
  try { localStorage.setItem(KEY, JSON.stringify(l)); } catch { /* storage unavailable */ }
}
export function resetLayout() {
  try { localStorage.removeItem(KEY); } catch { /* storage unavailable */ }
}
