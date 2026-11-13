// Effects are pinned to SOURCE time; these helpers project them onto the timeline
// (same rules as backend/app/effects.py map_to_timeline) and create new ones.
import { clipEnd, newId, topVideoClipAt, clipAt } from "./ops";
import type { Effect, EffectKind, Timeline } from "./types";

export interface Win { start: number; end: number }

export function effectWindows(tl: Timeline, e: Effect, kind: "video" | "audio"): Win[] {
  const out: Win[] = [];
  const s0 = e.source_time, s1 = e.source_time + e.duration;
  for (const t of tl.tracks) {
    if (t.kind !== kind || (kind === "video" ? t.hidden : t.muted)) continue;
    for (const c of t.clips) {
      if (c.media_id !== e.media_id) continue;
      const a = Math.max(s0, c.source_in), b = Math.min(s1, c.source_out);
      if (b - a <= 0.005) continue;
      const ws = c.start + (a - c.source_in) / c.speed;
      out.push({ start: ws, end: ws + (b - a) / c.speed });
    }
  }
  const seen = new Set<string>();
  return out.filter((w) => { const k = w.start.toFixed(3) + ":" + w.end.toFixed(3); if (seen.has(k)) return false; seen.add(k); return true; })
    .sort((a, b) => a.start - b.start);
}

export const isAudioFx = (k: EffectKind) => k === "censor" || k === "sfx" || k === "bass";

/** First place the effect appears in the edit, or null if that moment was cut. */
export function effectTime(tl: Timeline, e: Effect): number | null {
  const w = effectWindows(tl, e, isAudioFx(e.kind) ? "audio" : "video");
  const alt = w.length ? w : effectWindows(tl, e, isAudioFx(e.kind) ? "video" : "audio");
  return alt.length ? alt[0].start : null;
}

/** The footage at timeline time t that an effect of this kind pins to: the top visible
 *  video clip (or, for sounds and bleeps, the first unmuted audio clip first), else the
 *  other kind. Returns its media and the matching moment in that recording. */
export function anchorAt(tl: Timeline, t: number, kind: EffectKind): { media_id: string; source_time: number } | null {
  const video = () => topVideoClipAt(tl, t)?.clip ?? null;
  const audio = () => { for (const tr of tl.tracks) if (tr.kind === "audio" && !tr.muted) { const c = clipAt(tr, t); if (c) return c; } return null; };
  const hit = isAudioFx(kind) ? (audio() ?? video()) : (video() ?? audio());
  if (!hit) return null;
  return { media_id: hit.media_id, source_time: Math.max(0, +(hit.source_in + (t - hit.start) * hit.speed).toFixed(3)) };
}

/** Move an effect so it starts at timeline time t (re-pinned to the footage there). */
export function moveEffectTo(tl: Timeline, e: Effect, t: number): Effect | { error: string } {
  if (!Number.isFinite(t) || t < 0) return { error: "Type a time like 20.8 or 0:20.8" };
  const a = anchorAt(tl, t + 0.001, e.kind);
  if (!a) return { error: `There's no footage at ${t.toFixed(2)} s to put it on` };
  return { ...e, media_id: a.media_id, source_time: Math.max(0, +(a.source_time - 0.001).toFixed(3)) };
}

/** "20.8", "20.8s", "0:20.80", "1:02:03.5" -> seconds; null if it isn't a time. */
export function parseTime(text: string): number | null {
  const s = text.trim().replace(/s$/i, "").trim();
  if (!/^\d+(:\d{1,2}){0,2}(\.\d*)?$/.test(s) && !/^\.\d+$/.test(s)) return null;
  const parts = s.split(":");
  if (parts.slice(1).some((p) => parseFloat(p) >= 60)) return null;
  const v = parts.reduce((acc, p) => acc * 60 + parseFloat(p || "0"), 0);
  return Number.isFinite(v) ? v : null;
}

/** Anchor a new effect at timeline time t (top visible video clip, else audio). */
export function newEffectAt(tl: Timeline, t: number, kind: EffectKind, extra: Partial<Effect> = {}): Effect | null {
  let hit = topVideoClipAt(tl, t)?.clip ?? null;
  if (!hit) for (const tr of tl.tracks) if (tr.kind === "audio" && !tr.muted) { hit = clipAt(tr, t); if (hit) break; }
  if (!hit) return null;
  const src = hit.source_in + (t - hit.start) * hit.speed;
  const defaults: Record<EffectKind, Partial<Effect>> = {
    censor: { duration: 0.5, sound: "beep" }, zoom: { duration: 1.2, scale: 1.25 }, shake: { duration: 0.5, intensity: 0.6 },
    flash: { duration: 0.15 }, text: { duration: 1.3, text: "NO WAY", y: 0.22, size: 0.13, color: "#ffde00" },
    sfx: { duration: 0.6, sound: "boom" }, image: { duration: 1.5, size: 0.12, y: 0.35 },
    count: { duration: 0.6, sound: "ding" }, bass: { duration: 1.5, intensity: 1 },
  };
  return {
    id: newId(), kind, media_id: hit.media_id, source_time: Math.max(0, +src.toFixed(3)), duration: 1, enabled: true,
    origin: "user", sound: null, volume: 0.8, text: null, word: null, context: null, confidence: null, needs_review: false,
    scale: 1.25, intensity: 0.5, x: 0.5, y: 0.5, size: 0.12, color: "#ffffff", asset: null, ...defaults[kind], ...extra,
  };
}

export function activeEffects(tl: Timeline, effects: Effect[], t: number): { e: Effect; w: Win }[] {
  const out: { e: Effect; w: Win }[] = [];
  for (const e of effects) {
    if (!e.enabled) continue;
    for (const w of effectWindows(tl, e, isAudioFx(e.kind) ? "audio" : "video")) if (t >= w.start && t < w.end) out.push({ e, w });
  }
  return out;
}
export const _unused = clipEnd;
