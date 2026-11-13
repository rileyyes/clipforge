// Phase 18: counters, callout cards, combo effects, keep-only-the-funny-moments,
// who's talking (name tags) and text style presets. Same rules as the backend
// (backend/app/overlays.py counter_ticks, reactions.track_talk).
import { effectWindows, newEffectAt } from "./effects";
import { addTitle, cutRanges, newId, timelineDuration, type OpResult } from "./ops";
import type { Counter, Effect, Sound, TextStyle, Timeline, Title, Track } from "./types";

const round6 = (x: number) => Math.round(x * 1e6) / 1e6;
const HEX = /^#[0-9a-fA-F]{6}$/;

// ---------------------------------------------------------------- counters
export const MAX_COUNTERS = 4;

export function addCounter(tl: Timeline, label = "COUNT"): OpResult & { id?: string } {
  const list = tl.counters ?? [];
  if (list.length >= MAX_COUNTERS) return { error: `At most ${MAX_COUNTERS} counters` };
  // a second counter goes under the first so they don't sit on top of each other
  const c: Counter = { id: newId(), label, start_value: 0, start: 0, end: null, x: 0.86, y: 0.12 + list.length * 0.17,
    size: 1, color: "#ffffff", accent: "#e3242b", font: null };
  return { timeline: { ...tl, counters: [...list, c] }, id: c.id };
}

export function updateCounter(tl: Timeline, id: string, patch: Partial<Omit<Counter, "id">>): OpResult {
  const c = (tl.counters ?? []).find((x) => x.id === id);
  if (!c) return { error: "Counter not found" };
  const n: Counter = { ...c, ...patch };
  n.label = n.label.slice(0, 24);
  n.start_value = Math.max(0, Math.min(9999, Math.round(n.start_value)));
  n.start = round6(Math.max(0, n.start));
  if (n.end !== null && n.end <= n.start + 0.05) return { error: "The counter has to end after it starts" };
  n.x = Math.max(0, Math.min(1, n.x)); n.y = Math.max(0, Math.min(1, n.y));
  n.size = Math.max(0.5, Math.min(2, n.size));
  if (!HEX.test(n.color) || !HEX.test(n.accent)) return { error: "Colours must be like #e3242b" };
  return { timeline: { ...tl, counters: (tl.counters ?? []).map((x) => (x.id === id ? n : x)) } };
}

/** Removes the counter and every +1 that belonged to it. */
export function removeCounter(tl: Timeline, effects: Effect[], id: string): { timeline: Timeline; effects: Effect[] } {
  return { timeline: { ...tl, counters: (tl.counters ?? []).filter((c) => c.id !== id) },
           effects: effects.filter((e) => !(e.kind === "count" && e.counter === id)) };
}

/** Timeline times this counter goes up (each appearance of a count's moment counts). */
export function counterTicks(tl: Timeline, effects: Effect[], id: string): number[] {
  const out: number[] = [];
  for (const e of effects) {
    if (e.kind !== "count" || !e.enabled || e.counter !== id) continue;
    const w = effectWindows(tl, e, "video");
    out.push(...(w.length ? w : effectWindows(tl, e, "audio")).map((x) => x.start));
  }
  return out.sort((a, b) => a - b);
}

export function counterValue(c: Counter, ticks: number[], t: number): number {
  return c.start_value + ticks.filter((x) => x <= t + 1e-6).length;
}

/** A +1 for this counter pinned to the footage at t. */
export function countAt(tl: Timeline, counterId: string, t: number, sound: Sound | null = "ding"): Effect | { error: string } {
  const e = newEffectAt(tl, t, "count", { counter: counterId, duration: 0.6, sound, volume: 0.7 });
  return e ?? { error: "There's no footage at the playhead to count on" };
}

/** "Count it": +1 on the counter (made if there isn't one) and a callout card, at t. */
export function addCount(tl: Timeline, effects: Effect[], t: number, name: string, how: string, sound: Sound | null = "boom"):
  { timeline: Timeline; effects: Effect[]; titleId: string } | { error: string } {
  let cur = tl;
  let ctr = (cur.counters ?? [])[0];
  if (!ctr) {
    const r = addCounter(cur);
    if (r.error !== undefined) return { error: r.error };
    cur = r.timeline; ctr = cur.counters![0];
  }
  const e = countAt(cur, ctr.id, t, sound);
  if ("error" in e) return { error: e.error! };
  const r = addTitle(cur, "count_card", t);
  if (r.error !== undefined || !r.id) return { error: r.error ?? "Couldn't add the callout card" };
  const titles = r.timeline.titles!.map((x) => (x.id === r.id ? { ...x, text: (name || "Name").slice(0, 80), subtext: how.slice(0, 100) } : x));
  return { timeline: { ...r.timeline, titles }, effects: [...effects, e], titleId: r.id };
}

/** Callout cards in time order with their # (same numbering as the export). */
export function countCards(tl: Timeline): (Title & { n: number })[] {
  return (tl.titles ?? []).filter((t) => t.template === "count_card").sort((a, b) => a.start - b.start).map((t, i) => ({ ...t, n: i + 1 }));
}

/** What a tally shows: the callout cards before it and the total (its counter's value then, else how many). */
export function tallyInfo(tl: Timeline, effects: Effect[], tally: Title): { entries: [string, string][]; total: number } {
  const cards = countCards(tl);
  const before = cards.filter((c) => c.start < tally.start);
  const list = before.length ? before : cards;
  const ctr = (tl.counters ?? [])[0];
  const total = ctr ? counterValue(ctr, counterTicks(tl, effects, ctr.id), tally.start + 1e-3) : list.length;
  return { entries: list.map((c) => [c.text, c.subtext] as [string, string]), total };
}

// ---------------------------------------------------------------- combo effects
export interface Combo { id: string; label: string; hint: string; make: (tl: Timeline, t: number) => Effect[] }
const fx = (tl: Timeline, t: number, kind: Effect["kind"], extra: Partial<Effect> = {}) => newEffectAt(tl, t, kind, extra);
const all = (xs: (Effect | null)[]) => xs.filter((x): x is Effect => !!x);

export const COMBOS: Combo[] = [
  { id: "meme_zoom", label: "Meme zoom", hint: "Hard zoom + shake + boom",
    make: (tl, t) => all([fx(tl, t, "zoom", { scale: 1.6, duration: 0.9 }), fx(tl, t, "shake", { duration: 0.6, intensity: 0.8 }),
                          fx(tl, t, "sfx", { sound: "boom", duration: 0.9, volume: 0.9 })]) },
  { id: "bass_boosted", label: "Bass boosted", hint: "Crunchy bass + zoom + shake for 1.5 s",
    make: (tl, t) => all([fx(tl, t, "bass", { duration: 1.5, intensity: 1 }), fx(tl, t, "zoom", { scale: 1.35, duration: 1.5 }),
                          fx(tl, t, "shake", { duration: 1.5, intensity: 0.5 })]) },
  { id: "airhorn", label: "Airhorn hype", hint: "Flash + shake + airhorn",
    make: (tl, t) => all([fx(tl, t, "flash", { duration: 0.15 }), fx(tl, t, "shake", { duration: 0.8, intensity: 0.7 }),
                          fx(tl, t, "sfx", { sound: "airhorn", duration: 1.2, volume: 0.8 })]) },
  { id: "record_scratch", label: "Record scratch", hint: "Scratch + slow push-in",
    make: (tl, t) => all([fx(tl, t, "sfx", { sound: "scratch", duration: 0.7, volume: 0.9 }), fx(tl, t, "zoom", { scale: 1.15, duration: 2 })]) },
  { id: "bonk", label: "Bonk", hint: "Boing + quick shake",
    make: (tl, t) => all([fx(tl, t, "sfx", { sound: "boing", duration: 0.7, volume: 0.9 }), fx(tl, t, "shake", { duration: 0.35, intensity: 0.9 })]) },
];

// ---------------------------------------------------------------- funny moments
export interface Moment { start: number; end: number; reaction: number; score: number; people: number }

/** Cut everything except these stretches (the moments end up back to back, in order). */
export function keepOnly(tl: Timeline, keep: [number, number][]): OpResult {
  const D = timelineDuration(tl);
  const ks = [...keep].map(([a, b]) => [Math.max(0, a), Math.min(D, b)] as [number, number]).filter(([a, b]) => b - a > 0.05).sort((x, y) => x[0] - y[0]);
  if (!ks.length) return { error: "Pick at least one moment to keep" };
  const cut: [number, number][] = [];
  let pos = 0;
  for (const [a, b] of ks) {
    if (a > pos + 0.02) cut.push([pos, a]);
    pos = Math.max(pos, b);
  }
  if (D > pos + 0.02) cut.push([pos, D]);
  return cut.length ? cutRanges(tl, cut) : { error: "Those moments already cover the whole video" };
}

// ---------------------------------------------------------------- who's talking
/** Timeline stretches where this audio track is talking, from each recording's talking (source s). */
export function trackTalk(track: Track, talkByMedia: Record<string, [number, number][]>): [number, number][] {
  const out: [number, number][] = [];
  for (const c of [...track.clips].sort((a, b) => a.start - b.start)) {
    for (const [a0, b0] of talkByMedia[c.media_id] ?? []) {
      const a = Math.max(a0, c.source_in), b = Math.min(b0, c.source_out);
      if (b - a > 0.05) out.push([c.start + (a - c.source_in) / c.speed, c.start + (b - c.source_in) / c.speed]);
    }
  }
  return out;
}

export const taggedTracks = (tl: Timeline) =>
  tl.tracks.filter((t) => t.kind === "audio" && !t.muted && (t.tag ?? "").trim() && t.clips.length);

// ---------------------------------------------------------------- text styles
type Style = Omit<TextStyle, "name">;
const S = (s: Partial<Style>): Style => ({ font: null, color: "#ffffff", accent: "#ff5a3c", stroke: null, stroke_color: "#000000",
  shadow: null, glow: 0, glow_color: "#ffde00", ...s });
/** Ready-made looks (fonts are all built in). */
export const TEXT_PRESETS: TextStyle[] = [
  { name: "Bold outline", ...S({ font: "anton", color: "#ffde00", stroke: 9, shadow: 6 }) },
  { name: "Horror", ...S({ font: "creepster", color: "#e3242b", accent: "#e3242b", stroke: 5, glow: 14, glow_color: "#5a0000" }) },
  { name: "Blood drip", ...S({ font: "nosifer", color: "#ff2b2b", accent: "#ff2b2b", stroke: 3, shadow: 5 }) },
  { name: "Comic", ...S({ font: "bangers", color: "#ffffff", accent: "#ffde00", stroke: 8, stroke_color: "#1b1b1b", shadow: 7 }) },
  { name: "Cartoon", ...S({ font: "luckiest-guy", color: "#ffde00", accent: "#ff5a3c", stroke: 8, stroke_color: "#3b1a00" }) },
  { name: "Arcade", ...S({ font: "press-start", color: "#39ff14", accent: "#39ff14", stroke: 4, glow: 12, glow_color: "#39ff14" }) },
  { name: "Neon", ...S({ font: "monoton", color: "#ffffff", accent: "#ff2bd6", stroke: 0, glow: 22, glow_color: "#ff2bd6" }) },
  { name: "Glitch", ...S({ font: "rubik-glitch", color: "#ffffff", accent: "#00e5ff", stroke: 3, stroke_color: "#ff006e", shadow: 4 }) },
  { name: "Marker", ...S({ font: "permanent-marker", color: "#ffffff", accent: "#ff5a3c", stroke: 5, shadow: 4 }) },
  { name: "Clean", ...S({ font: "poppins", color: "#ffffff", accent: "#4cc9f0", stroke: 0, shadow: 3 }) },
];

export function styleOf(t: Title, name = ""): TextStyle {
  return { name, font: t.font ?? null, color: t.color, accent: t.accent, stroke: t.stroke ?? null, stroke_color: t.stroke_color ?? "#000000",
    shadow: t.shadow ?? null, glow: t.glow ?? 0, glow_color: t.glow_color ?? "#ffde00" };
}
export function applyStyle(s: TextStyle): Partial<Title> {
  const { name: _name, ...rest } = s;
  return rest;
}
