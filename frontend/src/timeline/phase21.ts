// Phase 21: multicam on the timeline. The backend (backend/app/multicam.py) lines the
// cameras up and decides which one shows from each moment of the main recording; this puts
// that onto the edit on the bottom video track, so cuts you already made stay where they are.
import { clipDuration, findClip, MIN_CLIP, round6, splitAt, type OpResult } from "./ops";
import { pyRound } from "./phase19";
import type { Clip, ColorAdjust, MediaMap, Multicam, Timeline, Title, Track } from "./types";

const EPS = 1e-6;

/** The bottom video track that's shown (the export's base picture). */
export function baseTrack(tl: Timeline): Track | undefined {
  return tl.tracks.find((t) => t.kind === "video" && !t.hidden);
}

/** Which camera a switch list shows at main-recording time t. */
export function angleAt(mc: Pick<Multicam, "switches">, t: number): number {
  let lo = 0, hi = mc.switches.length - 1, ans = 0;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (mc.switches[mid].t <= t + EPS) { ans = mc.switches[mid].angle; lo = mid + 1; } else hi = mid - 1;
  }
  return mc.switches.length ? ans : 0;
}

/** Index of the camera a clip shows (-1: not one of the cameras). */
export const angleOf = (mc: Multicam, c: Clip) => mc.angles.findIndex((a) => a.media_id === c.media_id);

/** The clip as if it showed the main recording (same moment). A camera clip that was trimmed
 *  to moments the main recording doesn't have stays as it is. */
function toMain(mc: Multicam, c: Clip, media?: MediaMap, tl?: Timeline): Clip {
  const i = angleOf(mc, c);
  if (i <= 0) return c;
  // its linked sound from the main recording says exactly which moment it is
  const partner = linkedFrom(tl, c, mc.main_media_id);
  if (partner) return { ...c, media_id: mc.main_media_id, source_in: partner.source_in, source_out: partner.source_out };
  const off = mc.angles[i].offset;
  const si = round6(c.source_in - off), so = round6(c.source_out - off);
  const dur = media?.[mc.main_media_id]?.duration;
  if (si < -EPS || (dur !== undefined && so > dur + EPS)) return c;
  return { ...c, media_id: mc.main_media_id, source_in: Math.max(0, si), source_out: so + (si < 0 ? -si : 0) };
}

/** A clip linked to ``c`` that plays ``mediaId`` (its picture/sound partner from that file). */
function linkedFrom(tl: Timeline | undefined, c: Clip, mediaId: string): Clip | undefined {
  return c.link_id && tl ? tl.tracks.flatMap((t) => t.clips).find((x) => x.id !== c.id && x.link_id === c.link_id && x.media_id === mediaId) : undefined;
}

/** Show camera ``angle`` in this clip, if that camera filmed the whole of it. */
function toAngle(mc: Multicam, c: Clip, angle: number, media: MediaMap, tl?: Timeline): Clip | null {
  const a = mc.angles[angle];
  if (!a) return null;
  if (angle === 0) return c;
  // linked to sound from that same camera: use exactly that moment (linked clips of one file stay in step)
  const partner = linkedFrom(tl, c, a.media_id);
  if (partner) return media[a.media_id]?.has_video ? { ...c, media_id: a.media_id, source_in: partner.source_in, source_out: partner.source_out } : null;
  const asset = media[a.media_id];
  const si = round6(c.source_in + a.offset), so = round6(c.source_out + a.offset);
  if (!asset || !asset.has_video || si < -EPS || so > asset.duration + EPS) return null;
  // (a tiny negative start is rounding: shift, never shrink, so linked sound stays the same length)
  return { ...c, media_id: a.media_id, source_in: Math.max(0, si), source_out: so + (si < 0 ? -si : 0) };
}

/** Put the multicam switches on the edit: every piece of the main recording (or of a
 *  camera, when applying again) on the bottom video track is split where the camera
 *  changes and shows that camera. Linked sound is split with it but keeps playing the
 *  main recording's sound. Where a camera didn't film that moment, the main one stays. */
export function applyMulticam(tl: Timeline, mc: Multicam, media: MediaMap): OpResult {
  if (mc.angles.length < 2) return { error: "Pick at least two cameras" };
  if (mc.angles[0].media_id !== mc.main_media_id) return { error: "The first camera must be the main recording" };
  const base = baseTrack(tl);
  if (!base) return { error: "There's no video track to put the cameras on" };
  if (base.locked) return { error: `Track ${base.name} is locked` };
  // 1. applying again: back to the main recording first, with the offsets it was applied with
  const old = tl.multicam;
  let out: Timeline = !old ? tl : { ...tl, tracks: tl.tracks.map((t) => (t.id !== base.id ? t
    : { ...t, clips: t.clips.map((c) => (angleOf(old, c) > 0 ? toMain(old, c, media, tl) : c)) })) };
  if (old && old.main_media_id !== mc.main_media_id) return { error: "Turn multicam off first to change the main camera" };
  const todo = out.tracks.find((t) => t.id === base.id)!.clips.filter((c) => c.media_id === mc.main_media_id).map((c) => c.id);
  if (!todo.length) return { error: "The main recording isn't on the bottom video track. Put it there first (or pick it as the main camera)." };
  let switched = 0;
  for (const id0 of todo) {
    // 2. split where the camera changes (in this clip's part of the main recording)
    let id = id0;
    const first = findClip(out, id)!.clip;
    const cuts = mc.switches.filter((s) => s.t > first.source_in + EPS && s.t < first.source_out - EPS).map((s) => s.t);
    for (const t of cuts) {
      const c = findClip(out, id)!.clip;
      const at = round6(c.start + (t - c.source_in) / c.speed);
      if (at - c.start < MIN_CLIP || c.start + clipDuration(c) - at < MIN_CLIP) continue;
      const r = splitAt(out, [id], at);
      if (r.error || !r.timeline) continue;
      out = r.timeline;
      id = r.created!.find((x) => findClip(out, x)?.track.id === base.id) ?? id;
    }
  }
  // 3. each piece shows its camera
  const tracks = out.tracks.map((t) => {
    if (t.id !== base.id) return t;
    return { ...t, clips: t.clips.map((c) => {
      if (c.media_id !== mc.main_media_id) return c;
      const mid = (c.source_in + c.source_out) / 2;
      const want = angleAt(mc, mid);
      const v = want > 0 ? toAngle(mc, c, want, media, out) : null;
      if (v) switched++;
      return v ?? c;
    }) };
  });
  return { timeline: { ...out, tracks, multicam: mc }, created: [], switched } as OpResult;
}

/** Show a different camera in one clip of the edit (pick by hand). */
export function setClipAngle(tl: Timeline, clipId: string, angle: number, media: MediaMap): OpResult {
  const mc = tl.multicam;
  if (!mc) return { error: "Turn multicam on first" };
  const ref = findClip(tl, clipId);
  if (!ref) return { error: "Clip not found" };
  if (ref.track.id !== baseTrack(tl)?.id || angleOf(mc, ref.clip) < 0) return { error: "Pick a multicam clip on the bottom video track" };
  if (ref.track.locked) return { error: `Track ${ref.track.name} is locked` };
  const main = toMain(mc, ref.clip, media, tl);
  if (angleOf(mc, main) !== 0) return { error: "This shot shows a moment the main camera didn't film" };
  const v = toAngle(mc, main, angle, media, tl);
  if (!v) return { error: `Camera ${angle + 1} didn't film this moment` };
  return { timeline: { ...tl, tracks: tl.tracks.map((t) => (t.id !== ref.track.id ? t
    : { ...t, clips: t.clips.map((c) => (c.id === clipId ? v : c)) })) } };
}

/** Back to one camera: every camera clip shows the main recording again (the splits stay;
 *  they don't change how it looks or sounds). */
export function removeMulticam(tl: Timeline, media?: MediaMap): OpResult {
  const mc = tl.multicam;
  if (!mc) return { error: "Multicam isn't on" };
  const base = baseTrack(tl);
  return { timeline: { ...tl, multicam: null, tracks: tl.tracks.map((t) => (t.id !== base?.id ? t
    : { ...t, clips: t.clips.map((c) => toMain(mc, c, media, tl)) })) } };
}

/** Labels like "Cam 2 · Sam". */
export const camLabel = (mc: Multicam, i: number) => `Cam ${i + 1}${mc.angles[i]?.label ? ` · ${mc.angles[i].label}` : ""}`;

// ---------------------------------------------------------------- motion graphics
// Same rules as the export (backend/app/titles.py, Phase 21), checked against
// backend/tests/data/motion_vectors.json.
export const BAR_GROW = 0.6, BAR_DELAY = 0.25, BAR_STAGGER = 0.12, BAR_ACCEL = 0.4;
export const RING_DELAY = 0.2, RING_GROW = 1.0, RING_STEPS = 30, STEP = 1 / 15;
const clamp01 = (x: number) => Math.min(1, Math.max(0, x));

export const barGrow = (tt: number, i: number) => Math.pow(clamp01((tt - BAR_DELAY - i * BAR_STAGGER) / BAR_GROW), BAR_ACCEL);

export function decimals(values: number[]): number {
  let d = 0;
  for (const v of values) {
    let k = 0;
    for (; k <= 2; k++) if (Math.abs(Math.round(v * 10 ** k) / 10 ** k - v) < 1e-9) break;
    d = Math.max(d, Math.min(k, 2));
  }
  return d;
}

export function fmtValue(v: number, fmt: string | undefined, dec = 0): string {
  const n = pyRound(v * 10 ** dec) / 10 ** dec;
  const body = Math.abs(n).toLocaleString("en-US", { minimumFractionDigits: dec, maximumFractionDigits: dec });
  const sign = n < 0 ? "-" : "";
  return fmt === "money" ? `${sign}$${body}` : fmt === "percent" ? `${sign}${body}%` : `${sign}${body}`;
}

export const ringProgress = (tt: number) => 1 - Math.pow(1 - clamp01((tt - RING_DELAY) / RING_GROW), 3);
export const ringValue = (tt: number, t: Pick<Title, "count_from" | "count_to">) =>
  (t.count_from ?? 0) + ((t.count_to ?? 0) - (t.count_from ?? 0)) * ringProgress(tt);
export function ringFraction(v: number, t: Pick<Title, "format" | "count_to">): number {
  if (t.format === "percent") return clamp01(v / 100);
  const to = t.count_to ?? 0;
  return to > 0 ? clamp01(v / to) : 0;
}
export const listDelay = (i: number, n: number, dur: number) => 0.35 + i * Math.min(0.6, Math.max(0.15, dur * 0.5 / Math.max(1, n)));

/** The time a rolling number shows (the export changes it STEP by STEP between t0 and t1). */
export function rollingTime(tt: number, t0: number, t1: number): number {
  const n = Math.max(1, Math.round((t1 - t0) / STEP));
  const d = (t1 - t0) / n;
  if (tt < t0 + d - 1e-9) return 0;
  return Math.min(t1, t0 + Math.floor((tt - t0) / d + 1e-9) * d);
}
/** The ring's fill as drawn by the export (RING_STEPS frames). */
export function ringDrawTime(tt: number): number {
  if (tt < RING_DELAY) return -1;
  return Math.min(RING_DELAY + RING_GROW, RING_DELAY + Math.floor((tt - RING_DELAY) / (RING_GROW / RING_STEPS) + 1e-9) * (RING_GROW / RING_STEPS));
}
export function endScreenBoxes(W: number, H: number) {
  const vw = W * 0.34, vh = vw * 9 / 16;
  return { videos: [[W * 0.31 - vw / 2, H * 0.47 - vh / 2, vw, vh], [W * 0.69 - vw / 2, H * 0.47 - vh / 2, vw, vh]] as [number, number, number, number][],
    subscribe: [W * 0.5, H * 0.82, H * 0.075] as [number, number, number] };
}

// ---------------------------------------------------------------- auto colour
/** Put automatic colour settings (per recording, from /color/auto) on every picture clip of
 *  that recording. Each clip keeps its own look (VHS, cinematic…). */
export function applyAutoColor(tl: Timeline, results: Record<string, ColorAdjust>): OpResult {
  const ids = Object.keys(results);
  if (!ids.length) return { error: "Nothing to change" };
  let n = 0;
  const tracks = tl.tracks.map((t) => (t.kind !== "video" || t.locked ? t : { ...t, clips: t.clips.map((c) => {
    const r = results[c.media_id];
    if (!r) return c;
    n++;
    const ok = (v: number, lo: number, hi: number, d: number) => (Number.isFinite(v) ? Math.max(lo, Math.min(hi, v)) : d);
    return { ...c, color: { brightness: ok(r.brightness, -1, 1, 0), contrast: ok(r.contrast, 0, 3, 1), saturation: ok(r.saturation, 0, 3, 1),
      gamma: ok(r.gamma, 0.1, 4, 1), temperature: ok(r.temperature, -1, 1, 0), look: c.color?.look ?? "none" } };
  }) }));
  if (!n) return { error: "None of those recordings is on an unlocked video track" };
  return { timeline: { ...tl, tracks } };
}
