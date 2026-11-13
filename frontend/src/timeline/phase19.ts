// Phase 19: timers & money counters (ticker), route drawing, slow push-in, automatic sound
// design and the pacing checker. Ticker and route rules are the same as backend/app/titles.py
// (checked against backend/tests/data/ticker_vectors.json).
import { effectWindows, newEffectAt } from "./effects";
import { clipEnd, findClip, timelineDuration, updateClip, type OpResult } from "./ops";
import type { Clip, Effect, Timeline, Title } from "./types";

const OUT = 0.3; // seconds of fade-out at the end of a title (titles.py OUT)

// ---------------------------------------------------------------- ticker
export function tickerValue(tt: number, t: Pick<Title, "duration" | "count_from" | "count_to" | "format">): number {
  const frm = t.count_from ?? 60, to = t.count_to ?? 0;
  const run = Math.max(0.05, t.duration - OUT);
  let p = Math.min(1, Math.max(0, tt / run));
  if ((t.format ?? "time") !== "time") p = 1 - Math.pow(1 - p, 3);
  return frm + (to - frm) * p;
}

export function tickerText(v: number, t: Pick<Title, "count_from" | "count_to" | "format">): string {
  const fmt = t.format ?? "time";
  const down = (t.count_to ?? 0) < (t.count_from ?? 60);
  if (fmt === "time") {
    const s0 = down ? Math.ceil(v - 1e-9) : Math.floor(v + 1e-9);
    const sign = s0 < 0 ? "-" : "", s = Math.abs(Math.trunc(s0));
    const h = Math.floor(s / 3600), m = Math.floor(s / 60) % 60, sec = s % 60;
    const pad = (n: number) => String(n).padStart(2, "0");
    return h ? `${sign}${h}:${pad(m)}:${pad(sec)}` : `${sign}${m}:${pad(sec)}`;
  }
  const n = pyRound(v);
  const body = Math.abs(n).toLocaleString("en-US");
  return (n < 0 ? "-" : "") + (fmt === "money" ? "$" : "") + body;
}

/** Python's round(): halves go to the even neighbour (so preview and export agree on .5). */
export function pyRound(v: number): number {
  const f = Math.floor(v), d = v - f;
  if (Math.abs(d - 0.5) < 1e-9) return f % 2 === 0 ? f : f + 1;
  return Math.round(v);
}

/** The text a ticker shows tt seconds into it (the end value once its count has finished). */
export function tickerAt(tt: number, t: Title): string {
  // the export samples the count every `step` seconds (titles.py ticker_steps): do the same
  const step = Math.max(1 / 15, t.duration / 3000);
  const q = Math.min(t.duration, Math.floor(tt / step + 1e-9) * step);
  return tickerText(tickerValue(q, t), t);
}

/** Last ten seconds of a countdown timer turn the accent colour. */
export function tickerHot(text: string, t: Title): boolean {
  if ((t.format ?? "time") !== "time" || !((t.count_to ?? 0) < (t.count_from ?? 60))) return false;
  const parts = text.replace(/^-/, "").split(":").map(Number);
  if (parts.some((x) => !Number.isFinite(x))) return false;
  return parts.reduce((a, p) => a * 60 + p, 0) <= 10;
}

/** A timer that runs in real time: its length matches the time it counts (+ the fade-out). */
export function realTimeDuration(t: Title): number {
  return Math.max(0.5, Math.min(600, Math.abs((t.count_to ?? 0) - (t.count_from ?? 60)) + OUT));
}

// ---------------------------------------------------------------- route
export function routeDrawTime(dur: number): number { return Math.min(2.0, Math.max(0.3, dur * 0.5)); }

/** The part of the route drawn after `f` (0-1) of its length: points (pixels) up to the tip. */
export function routePart(pts: [number, number][], f: number): [number, number][] {
  if (pts.length < 2) return pts.slice();
  const lens = pts.slice(1).map((p, i) => Math.hypot(p[0] - pts[i][0], p[1] - pts[i][1]));
  const total = lens.reduce((a, b) => a + b, 0) || 1;
  let want = total * Math.max(0, Math.min(1, f));
  const out: [number, number][] = [pts[0]];
  for (let i = 0; i < lens.length && want > 0; i++) {
    const u = want >= lens[i] ? 1 : want / lens[i];
    out.push([pts[i][0] + (pts[i + 1][0] - pts[i][0]) * u, pts[i][1] + (pts[i + 1][1] - pts[i][1]) * u]);
    want -= lens[i];
  }
  return out;
}

/** How much of a route is drawn tt seconds into it (in 30 steps, like the export). */
export function routeProgress(tt: number, dur: number): number {
  const steps = 30;
  return Math.min(1, Math.ceil(Math.max(1e-6, tt) / routeDrawTime(dur) * steps) / steps);
}

// ---------------------------------------------------------------- slow push-in / pull-out
export const PUSH = 1.12;
/** A slow, steady zoom over the whole clip (the "Ken Burns" move on stills and B-roll). */
export function slowPush(tl: Timeline, clipId: string, dir: "in" | "out" | "off"): OpResult {
  const ref = findClip(tl, clipId);
  if (!ref) return { error: "Clip not found" };
  if (ref.track.kind !== "video") return { error: "Pick a video clip" };
  const c = ref.clip;
  const kfs = { ...(c.keyframes ?? {}) };
  if (dir === "off") kfs.scale = [];   // an empty list clears that property's keyframes
  else {
    const base = c.transform.scale ?? 1;
    const [a, b] = dir === "in" ? [base, base * PUSH] : [base * PUSH, base];
    kfs.scale = [{ t: c.source_in, v: +a.toFixed(6), ease: "linear" }, { t: c.source_out, v: +b.toFixed(6), ease: "linear" }];
  }
  return updateClip(tl, clipId, { keyframes: kfs });
}

// ---------------------------------------------------------------- automatic sound design
export const SOUND_DESIGN = "sound design";   // Effect.context of the effects it adds
const BIG_TITLES = new Set(["big_title", "number_card", "chapter", "tally"]);
const POP_INS = new Set(["pop_text", "sticker", "stamp", "count_card"]);

/** Whooshes into transitions, zooms and pop-ups, a riser + hit into each marker, a hit on big titles.
 *  Replaces what it added before (your own effects are kept). */
export function soundDesign(tl: Timeline, effects: Effect[]): { effects: Effect[]; added: number } {
  const keep = effects.filter((e) => e.context !== SOUND_DESIGN);
  const made: Effect[] = [];
  const add = (t: number, sound: Effect["sound"], duration: number, volume: number) => {
    if (t < 0) return;
    const e = newEffectAt(tl, t + 0.001, "sfx", { sound, duration, volume, origin: "auto", context: SOUND_DESIGN });
    if (e && !made.some((m) => m.sound === sound && m.media_id === e.media_id && Math.abs(m.source_time - e.source_time) < 0.15)) made.push(e);
  };
  for (const tr of tl.tracks) {
    if (tr.kind !== "video" || tr.hidden) continue;
    for (const c of tr.clips) if (c.transition_in) add(c.start - c.transition_in.duration / 2 - 0.1, "whoosh", Math.max(0.4, c.transition_in.duration + 0.2), 0.5);
  }
  for (const e of keep) {
    if (!e.enabled || e.kind !== "zoom") continue;
    const w = effectWindows(tl, e, "video")[0];
    if (w) add(Math.max(0, w.start - 0.12), "whoosh", 0.35, 0.4);
  }
  for (const m of tl.markers ?? []) { add(m.t - 1.6, "riser", 1.6, 0.55); add(m.t, "impact", 0.8, 0.7); }
  for (const t of tl.titles ?? []) {
    if (BIG_TITLES.has(t.template)) add(t.start, "impact", 0.8, 0.6);
    else if (POP_INS.has(t.template)) add(Math.max(0, t.start - 0.05), "whoosh", 0.3, 0.35);
  }
  return { effects: [...keep, ...made], added: made.length };
}

// ---------------------------------------------------------------- pacing checker
export type Pace = "fast" | "lively" | "relaxed";
export const PACE_GAP: Record<Pace, number> = { fast: 2.5, lively: 4, relaxed: 8 };
export interface Stretch { start: number; end: number }

/** Moments the picture changes because of the edit: cuts (not a split that carries on), B-roll
 *  and other layers coming and going, transitions, titles, zooms/shakes/flashes/pop-ups.
 *  Plus stretches that are already moving: animated clips (keyframes) and, if given, busy footage. */
export function changeMoments(tl: Timeline, effects: Effect[], motion?: { step: number; values: number[] } | null):
  { events: number[]; moving: Stretch[] } {
  const events: number[] = [];
  const moving: Stretch[] = [];
  for (const tr of tl.tracks) {
    if (tr.kind !== "video" || tr.hidden) continue;
    const clips = [...tr.clips].sort((a, b) => a.start - b.start);
    clips.forEach((c, i) => {
      const prev = clips[i - 1];
      const carries = prev && prev.media_id === c.media_id && Math.abs(clipEnd(prev) - c.start) < 0.02
        && Math.abs(prev.source_out - c.source_in) < 0.02 && !c.transition_in;
      if (!carries) events.push(c.start);
      const next = clips[i + 1];
      if (!next || Math.abs(clipEnd(c) - next.start) > 0.02) events.push(clipEnd(c));
      if (animated(c)) moving.push({ start: c.start, end: clipEnd(c) });
    });
  }
  for (const t of tl.titles ?? []) events.push(t.start);
  for (const e of effects) {
    if (!e.enabled || !["zoom", "shake", "flash", "text", "image"].includes(e.kind)) continue;
    for (const w of effectWindows(tl, e, "video")) events.push(w.start);
  }
  if (motion) {
    let a: number | null = null;
    motion.values.forEach((v, i) => {
      const t = i * motion.step;
      if (v >= 0.35 && a === null) a = t;
      if (v < 0.35 && a !== null) { if (t - a >= 1) moving.push({ start: a, end: t }); a = null; }
    });
    if (a !== null) moving.push({ start: a, end: motion.values.length * motion.step });
  }
  return { events: events.filter((t) => t > 0.01).sort((a, b) => a - b), moving };
}

function animated(c: Clip): boolean {
  for (const p of ["scale", "x", "y", "rotation"] as const) {
    const k = c.keyframes?.[p];
    if (k && k.length >= 2 && Math.max(...k.map((x) => x.v)) - Math.min(...k.map((x) => x.v)) > (p === "scale" ? 0.03 : 4)) return true;
  }
  return false;
}

/** Stretches longer than the pace's gap where nothing changes on screen. */
export function slowStretches(tl: Timeline, effects: Effect[], pace: Pace, motion?: { step: number; values: number[] } | null): Stretch[] {
  const D = timelineDuration(tl);
  const gap = PACE_GAP[pace];
  const { events, moving } = changeMoments(tl, effects, motion);
  // every moment that is "covered": a change, or inside something already moving
  const marks = [0, ...events, D];
  const out: Stretch[] = [];
  for (let i = 0; i + 1 < marks.length; i++) {
    let a = marks[i];
    const b = marks[i + 1];
    // take the moving parts out of the quiet stretch
    for (const m of moving.filter((m) => m.end > a && m.start < b).sort((x, y) => x.start - y.start)) {
      if (m.start - a > gap) out.push({ start: a, end: m.start });
      a = Math.max(a, m.end);
    }
    if (b - a > gap) out.push({ start: +a.toFixed(3), end: +b.toFixed(3) });
  }
  return out;
}

/** 0-100: how much of the video is free of long still stretches. */
export function paceScore(tl: Timeline, stretches: Stretch[]): number {
  const D = timelineDuration(tl);
  if (D <= 0) return 100;
  const slow = stretches.reduce((a, s) => a + (s.end - s.start), 0);
  return Math.max(0, Math.round(100 * (1 - slow / D)));
}

/** Punch-ins spread through a slow stretch so no gap is longer than the pace allows. */
export function punchIns(tl: Timeline, s: Stretch, pace: Pace): Effect[] {
  const gap = PACE_GAP[pace];
  const n = Math.max(1, Math.ceil((s.end - s.start) / gap) - 1);
  const out: Effect[] = [];
  for (let i = 1; i <= n; i++) {
    const t = s.start + (s.end - s.start) * i / (n + 1);
    const e = newEffectAt(tl, t, "zoom", { scale: i % 2 ? 1.12 : 1.18, duration: Math.min(1.6, gap * 0.45), origin: "auto", context: "pacing" });
    if (e) out.push(e);
  }
  return out;
}
