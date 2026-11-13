// Phase 20: sound mixer and blend modes. Same rules as the export (backend/app/render.py:
// plan_render / mix_audio / blend_chain); the limits match backend/app/schema.py.
import { findClip, type OpResult } from "./ops";
import { BLEND_MODES, type BlendMode, type Timeline, type Track } from "./types";

export const MAX_TRACK_VOLUME = 2;
export const MAX_FX_VOLUME = 2;

const clamp = (v: number, lo: number, hi: number) => (Number.isFinite(v) ? Math.max(lo, Math.min(hi, v)) : 1);
const round3 = (v: number) => Math.round(v * 1000) / 1000;

/** Is any audio track soloed? Then only the solo tracks are heard. */
export const anySolo = (tl: Timeline) => tl.tracks.some((t) => t.kind === "audio" && !!t.solo);

/** How loud a whole audio track plays (0 = not heard): mute, solo and the mixer level. */
export function trackGain(tl: Timeline, t: Track): number {
  if (t.kind !== "audio" || t.muted) return 0;
  if (anySolo(tl) && !t.solo) return 0;
  return clamp(t.volume ?? 1, 0, MAX_TRACK_VOLUME);
}

export function setTrackMix(tl: Timeline, id: string, patch: { volume?: number; solo?: boolean; muted?: boolean }): OpResult {
  const t = tl.tracks.find((x) => x.id === id);
  if (!t) return { error: "Track not found" };
  if (t.kind !== "audio") return { error: "The mixer is for sound tracks" };
  const next: Track = { ...t };
  if (patch.volume !== undefined) next.volume = round3(clamp(patch.volume, 0, MAX_TRACK_VOLUME));
  if (patch.solo !== undefined) next.solo = patch.solo;
  if (patch.muted !== undefined) next.muted = patch.muted;
  return { timeline: { ...tl, tracks: tl.tracks.map((x) => (x.id === id ? next : x)) } };
}

/** Back to how it was recorded: every audio track at 100 %, no solo (mutes stay). */
export function resetMix(tl: Timeline): OpResult {
  return { timeline: { ...tl, tracks: tl.tracks.map((t) => (t.kind === "audio" ? { ...t, volume: 1, solo: false } : t)) } };
}

/** 1 → "0 dB", 0.5 → "−6 dB", 0 → "off". */
export function fmtDb(v: number): string {
  if (!(v > 0.0005)) return "off";
  const db = 20 * Math.log10(v);
  const r = Math.round(db);
  return `${r > 0 ? "+" : r < 0 ? "−" : ""}${Math.abs(r)} dB`;
}

export const clampFx = (v: number) => round3(clamp(v, 0, MAX_FX_VOLUME));

// ---------------------------------------------------------------- blend modes
export const BLEND_LABELS: Record<BlendMode, string> = {
  normal: "Normal", screen: "Screen (light only)", multiply: "Multiply (dark only)", overlay: "Overlay",
  lighten: "Lighten", darken: "Darken", addition: "Add (glow)", difference: "Difference", softlight: "Soft light",
};
export const BLEND_TIPS: Partial<Record<BlendMode, string>> = {
  screen: "Black disappears: for light leaks, fire, sparks, lens flares and dust shot on black",
  multiply: "White disappears: for paper textures, ink, shadows and dirt",
  overlay: "Adds the layer's contrast and colour: for grain, textures and colour washes",
  addition: "Brightens a lot: for glows and flashes",
  softlight: "A gentle overlay",
  difference: "Inverts where they differ: a trippy look",
};

/** The preview's CSS for a blend mode (the export uses FFmpeg's blend with the same formulas). */
export function cssBlend(mode: BlendMode | undefined): string | undefined {
  switch (mode ?? "normal") {
    case "normal": return undefined;
    case "addition": return "plus-lighter";
    case "softlight": return "soft-light";
    default: return mode;
  }
}

/** Blend modes only do something on an upper video track (they mix with the picture under it). */
export function canBlend(tl: Timeline, clipId: string): boolean {
  const ref = findClip(tl, clipId);
  if (!ref || ref.track.kind !== "video") return false;
  const vids = tl.tracks.filter((t) => t.kind === "video" && !t.hidden);   // the lowest one shown is the base
  return vids.indexOf(ref.track) > 0;
}

export function setBlend(tl: Timeline, ids: string[], mode: BlendMode): OpResult {
  if (!(BLEND_MODES as readonly string[]).includes(mode)) return { error: "Unknown blend mode" };
  const want = new Set(ids);
  if (!ids.length) return { error: "Select a clip first" };
  for (const id of ids) {
    const ref = findClip(tl, id);
    if (!ref) return { error: "Clip not found" };
    if (ref.track.locked) return { error: `Track ${ref.track.name} is locked` };
    if (ref.track.kind !== "video") return { error: "Blend modes are for pictures" };
  }
  return { timeline: { ...tl, tracks: tl.tracks.map((t) => (t.clips.some((c) => want.has(c.id))
    ? { ...t, clips: t.clips.map((c) => (want.has(c.id) ? { ...c, blend: mode } : c)) } : t)) } };
}
