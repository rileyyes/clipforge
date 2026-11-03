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

export const isAudioFx = (k: EffectKind) => k === "censor" || k === "sfx";

/** First place the effect appears in the edit, or null if that moment was cut. */
export function effectTime(tl: Timeline, e: Effect): number | null {
  const w = effectWindows(tl, e, isAudioFx(e.kind) ? "audio" : "video");
  const alt = w.length ? w : effectWindows(tl, e, isAudioFx(e.kind) ? "video" : "audio");
  return alt.length ? alt[0].start : null;
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
