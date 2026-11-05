// Pure, immutable timeline operations. Every edit in the UI goes through here,
// so these functions ARE the editing engine (and are unit-tested in ops.test.ts).
// Each returns { timeline } on success or { error } without changing anything.

import type { Clip, Crop, KfProp, Keyframe, MediaAsset, MediaMap, Timeline, Title, TitleTemplate, Track, TrackKind, Blur, BlurKey } from "./types";
import { KF_LIMITS } from "./keyframes";

export const MIN_CLIP = 0.04; // seconds; matches backend MIN_CLIP_DURATION
const EPS = 1e-6;

export type OpResult = { timeline: Timeline; error?: undefined; created?: string[] } | { error: string; timeline?: undefined; created?: undefined };

export function newId(): string {
  const c = (globalThis as any).crypto;
  if (c?.randomUUID) return c.randomUUID().replace(/-/g, "");
  let s = "";
  for (let i = 0; i < 32; i++) s += Math.floor(Math.random() * 16).toString(16);
  return s;
}

export const clipDuration = (c: Clip) => (c.source_out - c.source_in) / c.speed;
export const clipEnd = (c: Clip) => c.start + clipDuration(c);
export const round6 = (n: number) => Math.round(n * 1e6) / 1e6;

export function timelineDuration(tl: Timeline): number {
  let d = 0;
  for (const t of tl.tracks) for (const c of t.clips) d = Math.max(d, clipEnd(c));
  return d;
}

export function trackEnd(t: Track): number {
  return t.clips.reduce((m, c) => Math.max(m, clipEnd(c)), 0);
}

export interface ClipRef { track: Track; clip: Clip; ti: number }

export function findClip(tl: Timeline, id: string): ClipRef | null {
  for (let ti = 0; ti < tl.tracks.length; ti++) {
    const clip = tl.tracks[ti].clips.find((c) => c.id === id);
    if (clip) return { track: tl.tracks[ti], clip, ti };
  }
  return null;
}

/** The clip plus every clip sharing its link_id (e.g. a video clip and its audio). */
export function linkedGroup(tl: Timeline, id: string): ClipRef[] {
  const ref = findClip(tl, id);
  if (!ref) return [];
  if (!ref.clip.link_id) return [ref];
  const out: ClipRef[] = [];
  tl.tracks.forEach((track, ti) =>
    track.clips.forEach((clip) => { if (clip.link_id === ref.clip.link_id) out.push({ track, clip, ti }); }));
  return out;
}

export function expandLinked(tl: Timeline, ids: string[]): Set<string> {
  const s = new Set<string>();
  for (const id of ids) for (const r of linkedGroup(tl, id)) s.add(r.clip.id);
  return s;
}

function overlaps(track: Track, start: number, end: number, ignore: Set<string>): boolean {
  return track.clips.some((c) => !ignore.has(c.id) && start < clipEnd(c) - EPS && end > c.start + EPS);
}

function sortClips(clips: Clip[]): Clip[] {
  return [...clips].sort((a, b) => a.start - b.start);
}

function withTracks(tl: Timeline, map: (t: Track, i: number) => Track): Timeline {
  return { ...tl, tracks: tl.tracks.map(map) };
}

function lockedError(refs: ClipRef[]): string | null {
  return refs.some((r) => r.track.locked) ? `Track ${refs.find((r) => r.track.locked)!.track.name} is locked` : null;
}

// ---------------------------------------------------------------- add media

export function addMedia(tl: Timeline, media: MediaAsset, at?: number, videoTrackId?: string): OpResult {
  const vTrack = media.has_video
    ? tl.tracks.find((t) => t.id === videoTrackId && t.kind === "video") ?? tl.tracks.find((t) => t.kind === "video")
    : undefined;
  const aTrack = media.has_audio ? tl.tracks.find((t) => t.kind === "audio") : undefined;
  if (media.has_video && !vTrack) return { error: "Add a video track first" };
  if (media.has_audio && !media.has_video && !aTrack) return { error: "Add an audio track first" };
  const targets = [vTrack, aTrack].filter(Boolean) as Track[];
  if (targets.some((t) => t.locked)) return { error: "Target track is locked" };
  const start = round6(at ?? Math.max(...targets.map(trackEnd)));
  const dur = media.duration;
  for (const t of targets) if (overlaps(t, start, start + dur, new Set())) return { error: `Not enough room on ${t.name} at that position` };
  const link = targets.length > 1 ? newId() : null;
  const created: string[] = [];
  const timeline = withTracks(tl, (t) => {
    if (!targets.includes(t)) return t;
    const clip: Clip = {
      id: newId(), media_id: media.id, start, source_in: 0, source_out: round6(dur), speed: 1,
      volume: 1, transform: { x: 0, y: 0, scale: 1, rotation: 0 }, link_id: link, label: null,
    };
    created.push(clip.id);
    return { ...t, clips: sortClips([...t.clips, clip]) };
  });
  return { timeline, created };
}

// ---------------------------------------------------------------- split

export function splitAt(tl: Timeline, ids: string[], t: number): OpResult {
  const group = [...expandLinked(tl, ids)].map((id) => findClip(tl, id)!).filter(
    (r) => t > r.clip.start + MIN_CLIP - EPS && t < clipEnd(r.clip) - MIN_CLIP + EPS);
  if (!group.length) return { error: "Playhead must be inside the selected clip to split" };
  const le = lockedError(group);
  if (le) return { error: le };
  const newLinks = new Map<string, string>();
  const created: string[] = [];
  const affected = new Set(group.map((r) => r.clip.id));
  const timeline = withTracks(tl, (track) => {
    if (!track.clips.some((c) => affected.has(c.id))) return track;
    const clips: Clip[] = [];
    for (const c of track.clips) {
      if (!affected.has(c.id)) { clips.push(c); continue; }
      const cut = round6(c.source_in + (t - c.start) * c.speed);
      let link: string | null = null;
      if (c.link_id) {
        if (!newLinks.has(c.link_id)) newLinks.set(c.link_id, newId());
        link = newLinks.get(c.link_id)!;
      }
      // the left part keeps the start (fade in / transition), the right part keeps the end (fade out)
      const right: Clip = { ...c, id: newId(), start: round6(t), source_in: cut, link_id: link,
        transition_in: null, fade_in: 0, fade_out: c.fade_out ?? 0 };
      created.push(right.id);
      clips.push({ ...c, source_out: cut, fade_out: 0 }, right);
    }
    return { ...track, clips: sortClips(clips) };
  });
  return { timeline, created };
}

// ---------------------------------------------------------------- trim

/** Trim the start or end edge of a clip (and its linked clips) to `time`.
 *  The requested time is clamped to what's legal (media bounds, neighbours, min length). */
export function trimEdge(tl: Timeline, id: string, edge: "start" | "end", time: number, media: MediaMap): OpResult {
  const group = linkedGroup(tl, id);
  const primary = group.find((r) => r.clip.id === id);
  if (!primary) return { error: "Clip not found" };
  const le = lockedError(group);
  if (le) return { error: le };
  const base = edge === "start" ? primary.clip.start : clipEnd(primary.clip);
  let delta = time - base;
  let lo = -Infinity, hi = Infinity;
  for (const { track, clip } of group) {
    const m = media[clip.media_id];
    const others = track.clips.filter((c) => c.id !== clip.id);
    if (edge === "start") {
      const prevEnd = Math.max(0, ...others.filter((c) => c.start < clip.start).map(clipEnd));
      lo = Math.max(lo, prevEnd - clip.start, -clip.source_in / clip.speed);
      hi = Math.min(hi, clipDuration(clip) - MIN_CLIP);
    } else {
      // neighbours by order (start), not by comparing nearly-equal float edges
      const nextStart = Math.min(Infinity, ...others.filter((c) => c.start > clip.start).map((c) => c.start));
      hi = Math.min(hi, nextStart - clipEnd(clip), m ? (m.duration - clip.source_out) / clip.speed : Infinity);
      lo = Math.max(lo, MIN_CLIP - clipDuration(clip));
    }
  }
  if (lo > hi + EPS) return { error: "No room to trim" };
  delta = Math.min(hi, Math.max(lo, delta));
  if (Math.abs(delta) < EPS) return { timeline: tl };
  const ids = new Set(group.map((r) => r.clip.id));
  return {
    timeline: withTracks(tl, (track) => ({
      ...track,
      clips: track.clips.map((c) => {
        if (!ids.has(c.id)) return c;
        return edge === "start"
          ? { ...c, start: round6(c.start + delta), source_in: round6(c.source_in + delta * c.speed) }
          : { ...c, source_out: round6(c.source_out + delta * c.speed) };
      }),
    })),
  };
}

// ---------------------------------------------------------------- move

/** Move a clip (with its linked clips) to `newStart`. Optionally move the primary
 *  clip to another track of the same kind. Rejects overlaps instead of overwriting. */
export function moveClip(tl: Timeline, id: string, newStart: number, targetTrackId?: string): OpResult {
  const group = linkedGroup(tl, id);
  const primary = group.find((r) => r.clip.id === id);
  if (!primary) return { error: "Clip not found" };
  let delta = newStart - primary.clip.start;
  const minStart = Math.min(...group.map((r) => r.clip.start));
  if (minStart + delta < 0) delta = -minStart;
  const target = targetTrackId ? tl.tracks.find((t) => t.id === targetTrackId) : primary.track;
  if (!target) return { error: "Track not found" };
  if (target.kind !== primary.track.kind) return { error: `Can't put a ${primary.track.kind} clip on an ${target.kind} track` };
  const le = lockedError(group) ?? (target.locked ? `Track ${target.name} is locked` : null);
  if (le) return { error: le };
  const ids = new Set(group.map((r) => r.clip.id));
  for (const r of group) {
    const dest = r.clip.id === id ? target : r.track;
    const s = r.clip.start + delta;
    if (overlaps(dest, s, s + clipDuration(r.clip), ids)) return { error: `Clips can't overlap on ${dest.name}` };
  }
  const moved = new Map(group.map((r) => [r.clip.id, { ...r.clip, start: round6(r.clip.start + delta) }]));
  return {
    timeline: withTracks(tl, (track) => {
      let clips = track.clips.filter((c) => !(c.id === id && track.id !== target.id));
      clips = clips.map((c) => moved.get(c.id) ?? c);
      if (track.id === target.id && track.id !== primary.track.id) clips.push(moved.get(id)!);
      return { ...track, clips: sortClips(clips) };
    }),
  };
}

// ---------------------------------------------------------------- delete / ripple

export function deleteClips(tl: Timeline, ids: string[], ripple = false): OpResult {
  const all = expandLinked(tl, ids);
  if (!all.size) return { error: "Nothing selected" };
  const refs = [...all].map((i) => findClip(tl, i)!);
  const le = lockedError(refs);
  if (le) return { error: le };
  const removed = withTracks(tl, (track) =>
    track.clips.some((c) => all.has(c.id)) ? { ...track, clips: track.clips.filter((c) => !all.has(c.id)) } : track);
  if (!ripple) return { timeline: removed };

  // Ripple: close only the time that is now empty on EVERY track, and shift every
  // track by the same amount, so linked picture/sound and other tracks stay in sync.
  const holes = emptySpans(removed, refs.map((r) => [r.clip.start, clipEnd(r.clip)] as [number, number]));
  if (!holes.length) return { timeline: removed };
  const shiftAt = (t: number) => holes.reduce((s, [a, b]) => (b <= t + EPS ? s + (b - a) : s), 0);
  const firstHole = holes[0][0];
  const blocked = removed.tracks.find((t) => t.locked && t.clips.some((c) => c.start >= firstHole - EPS && shiftAt(c.start) > EPS));
  if (blocked) return { error: `Ripple would move clips on locked track ${blocked.name}` };
  // titles and blurs move with the picture (one that started in a closed gap starts where it was)
  const newTime = (t: number) => {
    const inHole = holes.find(([a, b]) => t > a + EPS && t < b - EPS);
    const at = inHole ? inHole[0] : t;
    return round6(Math.max(0, at - shiftAt(at)));
  };
  const moved = withTracks(removed, (track) => ({
    ...track,
    clips: track.clips.map((c) => {
      const sh = shiftAt(c.start);
      return sh > EPS ? { ...c, start: round6(Math.max(0, c.start - sh)) } : c;
    }),
  }));
  return {
    timeline: {
      ...moved,
      ...(removed.titles ? { titles: removed.titles.map((t) => ({ ...t, start: newTime(t.start) })) } : {}),
      ...(removed.blurs ? { blurs: removed.blurs.map((b) => shiftBlur(b, newTime(b.start) - b.start)) } : {}),
    },
  };
}

/** Parts of the given ranges that no remaining clip on any track covers (merged, sorted). */
function emptySpans(tl: Timeline, ranges: [number, number][]): [number, number][] {
  const merged: [number, number][] = [];
  for (const [a, b] of [...ranges].sort((x, y) => x[0] - y[0])) {
    const last = merged[merged.length - 1];
    if (last && a <= last[1] + EPS) last[1] = Math.max(last[1], b); else merged.push([a, b]);
  }
  const occupied = tl.tracks.flatMap((t) => t.clips.map((c) => [c.start, clipEnd(c)] as [number, number]));
  const out: [number, number][] = [];
  for (const [a, b] of merged) {
    let pieces: [number, number][] = [[a, b]];
    for (const [oa, ob] of occupied) {
      pieces = pieces.flatMap(([pa, pb]) => {
        if (ob <= pa + EPS || oa >= pb - EPS) return [[pa, pb]] as [number, number][];
        const keep: [number, number][] = [];
        if (oa > pa + EPS) keep.push([pa, oa]);
        if (ob < pb - EPS) keep.push([ob, pb]);
        return keep;
      });
    }
    out.push(...pieces.filter(([pa, pb]) => pb - pa > EPS));
  }
  return out;
}

// ---------------------------------------------------------------- duplicate

export function duplicateClip(tl: Timeline, id: string): OpResult {
  const group = linkedGroup(tl, id);
  if (!group.length) return { error: "Clip not found" };
  const groupStart = Math.min(...group.map((r) => r.clip.start));
  let start = Math.max(...group.map((r) => clipEnd(r.clip)));
  // walk forward until every copy fits on its track
  for (let guard = 0; guard < 10000; guard++) {
    const blocker = group
      .map((r) => {
        const s = start + (r.clip.start - groupStart);
        const e = s + clipDuration(r.clip);
        return r.track.clips.find((c) => s < clipEnd(c) - EPS && e > c.start + EPS);
      })
      .find(Boolean);
    if (!blocker) break;
    start = clipEnd(blocker);
  }
  const link = group.length > 1 ? newId() : null;
  const created: string[] = [];
  const copies = new Map<string, Clip>();
  for (const r of group) {
    const c: Clip = { ...r.clip, id: newId(), start: round6(start + (r.clip.start - groupStart)), link_id: link };
    copies.set(r.track.id + ":" + r.clip.id, c);
    created.push(c.id);
  }
  const le = lockedError(group);
  if (le) return { error: le };
  return {
    created,
    timeline: withTracks(tl, (track) => {
      const add = group.filter((r) => r.track.id === track.id).map((r) => copies.get(track.id + ":" + r.clip.id)!);
      return add.length ? { ...track, clips: sortClips([...track.clips, ...add]) } : track;
    }),
  };
}

// ---------------------------------------------------------------- properties

export interface ClipPatch {
  volume?: number; speed?: number; label?: string | null; transform?: Partial<Clip["transform"]>;
  crop?: Clip["crop"]; color?: Clip["color"]; keyframes?: Clip["keyframes"];
}

/** Same rules as the server: known properties, time order ≥ 1 ms apart, values in range, ≤ 64 each. */
export function keyframeProblem(kf: NonNullable<ClipPatch["keyframes"]>): string | null {
  for (const [prop, list] of Object.entries(kf) as [KfProp, Keyframe[] | undefined][]) {
    const lim = KF_LIMITS[prop];
    if (!lim) return `'${prop}' can't be keyframed`;
    if (!list?.length) continue;
    if (list.length > 64) return "At most 64 keyframes per property";
    for (let i = 0; i < list.length; i++) {
      const k = list[i];
      if (!Number.isFinite(k.t) || !Number.isFinite(k.v) || k.t < 0) return "Invalid keyframe";
      if (k.v < lim[0] || k.v > lim[1]) return `${prop} keyframe is out of range`;
      if (i && k.t - list[i - 1].t < 0.001) return "Keyframes must be in time order";
    }
  }
  return null;
}

export function updateClip(tl: Timeline, id: string, patch: ClipPatch): OpResult {
  const ref = findClip(tl, id);
  if (!ref) return { error: "Clip not found" };
  // speed must stay identical across linked clips to keep picture and sound in sync
  const targets = patch.speed !== undefined ? linkedGroup(tl, id) : [ref];
  const le = lockedError(targets);
  if (le) return { error: le };
  if (patch.speed !== undefined && (patch.speed < 0.25 || patch.speed > 4)) return { error: "Speed must be between 0.25x and 4x" };
  if (patch.volume !== undefined && (patch.volume < 0 || patch.volume > 4)) return { error: "Volume must be between 0 and 400%" };
  if (patch.transform?.scale !== undefined && (patch.transform.scale <= 0.01 || patch.transform.scale > 10)) return { error: "Scale must be between 1% and 1000%" };
  if (patch.transform?.rotation !== undefined && Math.abs(patch.transform.rotation) > 3600) return { error: "Rotation must be within ±3600°" };
  if (patch.transform?.opacity !== undefined && (patch.transform.opacity < 0 || patch.transform.opacity > 1)) return { error: "Opacity must be between 0 and 100%" };
  if (patch.crop && (patch.crop.left + patch.crop.right > 0.9 + EPS || patch.crop.top + patch.crop.bottom > 0.9 + EPS)) return { error: "Crop must leave at least 10% of the picture" };
  if (patch.keyframes) {
    const bad = keyframeProblem(patch.keyframes);
    if (bad) return { error: bad };
  }
  if (patch.color) {
    const c = patch.color;
    if (Math.abs(c.brightness) > 1 || c.contrast < 0 || c.contrast > 3 || c.saturation < 0 || c.saturation > 3
      || c.gamma < 0.1 || c.gamma > 4 || Math.abs(c.temperature) > 1) return { error: "Colour value out of range" };
  }
  if (patch.crop && Object.values(patch.crop).some((v) => !(v >= 0 && v <= 0.9))) return { error: "Crop must be between 0 and 90%" };
  if (patch.keyframes && Object.keys(patch.keyframes).some((k) => (ref.track.kind === "video") === (k === "volume"))) return { error: ref.track.kind === "video" ? "Volume keyframes go on the audio clip" : "Only volume can be keyframed on audio" };
  if (patch.speed !== undefined && targets.some((r) => (r.clip.source_out - r.clip.source_in) / patch.speed! < MIN_CLIP - EPS))
    return { error: "Clip would be too short at that speed" };
  const ids = new Set(targets.map((r) => r.clip.id));
  const next = withTracks(tl, (track) => ({
    ...track,
    clips: track.clips.map((c) => {
      if (!ids.has(c.id)) return c;
      const u: Clip = { ...c };
      if (patch.speed !== undefined) u.speed = patch.speed;
      if (c.id === id) {
        if (patch.volume !== undefined) u.volume = patch.volume;
        if (patch.label !== undefined) u.label = patch.label;
        if (patch.transform) u.transform = { ...c.transform, ...patch.transform };
        if (patch.crop) u.crop = patch.crop;
        if (patch.color) u.color = patch.color;
        if (patch.keyframes) {
          const kf = { ...(c.keyframes ?? {}), ...patch.keyframes };
          for (const k of Object.keys(kf) as (keyof typeof kf)[]) if (!kf[k]?.length) delete kf[k];
          u.keyframes = kf;
        }
      }
      return u;
    }),
  }));
  if (patch.speed !== undefined) {
    for (const r of targets) {
      const t = next.tracks[r.ti];
      const c = t.clips.find((x) => x.id === r.clip.id)!;
      if (overlaps(t, c.start, clipEnd(c), new Set([c.id]))) return { error: "Slowing down would overlap the next clip" };
    }
  }
  return { timeline: next };
}

// ---------------------------------------------------------------- tracks

export function addTrack(tl: Timeline, kind: TrackKind): OpResult {
  if (tl.tracks.length >= 32) return { error: "Track limit reached" };
  const n = tl.tracks.filter((t) => t.kind === kind).length + 1;
  const track: Track = { id: newId(), kind, name: `${kind === "video" ? "V" : "A"}${n}`, muted: false, hidden: false, locked: false, clips: [] };
  // keep video tracks before audio tracks
  const tracks = kind === "video"
    ? [...tl.tracks.filter((t) => t.kind === "video"), track, ...tl.tracks.filter((t) => t.kind === "audio")]
    : [...tl.tracks, track];
  return { timeline: { ...tl, tracks } };
}

export function removeTrack(tl: Timeline, trackId: string): OpResult {
  const t = tl.tracks.find((x) => x.id === trackId);
  if (!t) return { error: "Track not found" };
  if (t.clips.length) return { error: "Only empty tracks can be removed" };
  if (tl.tracks.filter((x) => x.kind === t.kind).length <= 1) return { error: `Keep at least one ${t.kind} track` };
  return { timeline: { ...tl, tracks: tl.tracks.filter((x) => x.id !== trackId) } };
}

export function toggleTrack(tl: Timeline, trackId: string, flag: "muted" | "hidden" | "locked"): OpResult {
  return { timeline: withTracks(tl, (t) => (t.id === trackId ? { ...t, [flag]: !t[flag] } : t)) };
}

// ---------------------------------------------------------------- snapping

export function snapPoints(tl: Timeline, exclude: Set<string>, playhead: number): number[] {
  const pts = [0, playhead];
  for (const t of tl.tracks) for (const c of t.clips) if (!exclude.has(c.id)) pts.push(c.start, clipEnd(c));
  return pts;
}

/** Snap `t` to the nearest point within `threshold` seconds. */
export function snap(t: number, points: number[], threshold: number): number {
  let best = t, dist = threshold;
  for (const p of points) {
    const d = Math.abs(p - t);
    if (d < dist) { dist = d; best = p; }
  }
  return best;
}

/** Which clip (top-most visible video track first) is under time `t`? */
export function topVideoClipAt(tl: Timeline, t: number): { clip: Clip; track: Track } | null {
  const vids = tl.tracks.filter((x) => x.kind === "video" && !x.hidden);
  for (let i = vids.length - 1; i >= 0; i--) {
    const c = vids[i].clips.find((c) => t >= c.start - EPS && t < clipEnd(c) - EPS);
    if (c) return { clip: c, track: vids[i] };
  }
  return null;
}

export function clipAt(track: Track, t: number): Clip | null {
  return track.clips.find((c) => t >= c.start - EPS && t < clipEnd(c) - EPS) ?? null;
}

export function sourceTimeAt(c: Clip, t: number): number {
  return c.source_in + (t - c.start) * c.speed;
}

// ---------------------------------------------------------------- transitions & fades

/** Keep fades and transitions valid after any edit (the server enforces the same rules):
 *  fade in + fade out <= clip length; transitions only on video clips and at most 90% of
 *  the clip (and of the clip directly before it); too-short transitions are removed. */
export function sanitize(tl: Timeline): Timeline {
  let changed = false;
  const tracks = tl.tracks.map((t) => {
    const sorted = [...t.clips].sort((a, b) => a.start - b.start);
    const clips = t.clips.map((c) => {
      const d = clipDuration(c);
      let u: Clip = c;
      const fi = c.fade_in ?? 0, fo = c.fade_out ?? 0;
      if (fi + fo > d + 1e-6) { const k = d / (fi + fo); u = { ...u, fade_in: round6(fi * k * 0.999), fade_out: round6(fo * k * 0.999) }; }
      if (u.transition_in) {
        if (t.kind !== "video") u = { ...u, transition_in: null };
        else {
          const prev = sorted.find((p) => p.id !== c.id && Math.abs(clipEnd(p) - c.start) < 0.02);
          const max = Math.min(d * 0.9, prev ? clipDuration(prev) * 0.9 : Infinity, 3);
          if (max < 0.1) u = { ...u, transition_in: null };
          else if (u.transition_in.duration > max) u = { ...u, transition_in: { ...u.transition_in, duration: Math.floor(max * 1e6) / 1e6 } };
        }
      }
      if (u !== c) changed = true;
      return u;
    });
    return changed ? { ...t, clips } : t;
  });
  return changed ? { ...tl, tracks } : tl;
}

export function setTransition(tl: Timeline, id: string, tr: Clip["transition_in"]): OpResult {
  const ref = findClip(tl, id);
  if (!ref) return { error: "Clip not found" };
  if (ref.track.locked) return { error: `Track ${ref.track.name} is locked` };
  if (tr && ref.track.kind !== "video") return { error: "Transitions go on video clips (the linked audio follows)" };
  const timeline = withTracks(tl, (t) => ({ ...t, clips: t.clips.map((c) => (c.id === id ? { ...c, transition_in: tr } : c)) }));
  return { timeline: sanitize(timeline) };
}

export function setFades(tl: Timeline, id: string, fade_in: number, fade_out: number): OpResult {
  const ref = findClip(tl, id);
  if (!ref) return { error: "Clip not found" };
  if (ref.track.locked) return { error: `Track ${ref.track.name} is locked` };
  const fi = Math.max(0, Math.min(10, fade_in)), fo = Math.max(0, Math.min(10, fade_out));
  const timeline = withTracks(tl, (t) => ({ ...t, clips: t.clips.map((c) => (c.id === id ? { ...c, fade_in: round6(fi), fade_out: round6(fo) } : c)) }));
  return { timeline: sanitize(timeline) };
}

export function setTrackRole(tl: Timeline, id: string, role: "dialogue" | "music"): OpResult {
  return { timeline: withTracks(tl, (t) => (t.id === id && t.kind === "audio" ? { ...t, role } : t)) };
}

// ---------------------------------------------------------------- smoother jump cuts
// Same rules as backend/app/jumpcuts.py (both checked against tests/data/jumpcut_vectors.json).
export type JumpCutMode = "off" | "punch" | "blend" | "whip";
export const JUMP_PUNCH = 0.055;   // crop each side -> ~1.12x zoom
const JUMP_BLEND = { kind: "crossfade", duration: 0.12 } as const;
const JUMP_WHIP = 0.25;

const isPunch = (c?: Crop) => !!c && (["left", "right", "top", "bottom"] as const).every((k) => Math.abs((c[k] ?? 0) - JUMP_PUNCH) < 1e-6);
const isPlain = (c?: Crop) => !c || (["left", "right", "top", "bottom"] as const).every((k) => Math.abs(c[k] ?? 0) < 1e-6);
const ourTransition = (t?: Clip["transition_in"]) => !!t && (
  (t.kind === JUMP_BLEND.kind && Math.abs(t.duration - JUMP_BLEND.duration) < 1e-6) ||
  ((t.kind === "whip_left" || t.kind === "whip_right") && Math.abs(t.duration - JUMP_WHIP) < 1e-6));
const clipDur = (c: Clip) => (c.source_out - c.source_in) / (c.speed ?? 1);

/** Back-to-back clips of the same footage with a stretch cut out between them (indexes into the start-sorted list). */
export function jumpPairs(clips: Clip[]): [number, number][] {
  const out: [number, number][] = [];
  for (let i = 0; i + 1 < clips.length; i++) {
    const a = clips[i], b = clips[i + 1];
    if (a.media_id === b.media_id && Math.abs(b.start - (a.start + clipDur(a))) < 0.02 && b.source_in - a.source_out > 0.04) out.push([i, i + 1]);
  }
  return out;
}

export function smoothJumpCuts(tl: Timeline, mode: JumpCutMode): OpResult & { count?: number } {
  const vi = tl.tracks.findIndex((t) => t.kind === "video");
  if (vi < 0) return { error: "No video track" };
  if (tl.tracks[vi].locked) return { error: `Track ${tl.tracks[vi].name} is locked` };
  const clips = [...tl.tracks[vi].clips].sort((a, b) => a.start - b.start).map((c) => {
    const n: Clip = { ...c };
    if (isPunch(n.crop)) n.crop = { left: 0, right: 0, top: 0, bottom: 0 };
    if (ourTransition(n.transition_in)) n.transition_in = null;
    return n;
  });
  const pairs = jumpPairs(clips);
  let count = 0;
  if (mode === "punch") {
    const pos = new Map<number, number>();
    for (const [i, j] of pairs) { if (!pos.has(i)) pos.set(i, 0); pos.set(j, pos.get(i)! + 1); }
    for (const [idx, p] of pos) {
      if (p % 2 === 1 && isPlain(clips[idx].crop)) {
        clips[idx] = { ...clips[idx], crop: { left: JUMP_PUNCH, right: JUMP_PUNCH, top: JUMP_PUNCH, bottom: JUMP_PUNCH } };
        count++;
      }
    }
  } else if (mode === "blend" || mode === "whip") {
    let k = 0;
    const d = mode === "blend" ? JUMP_BLEND.duration : JUMP_WHIP;
    for (const [i, j] of pairs) {
      const a = clips[i], b = clips[j];
      if (b.transition_in || Math.min(clipDur(a), clipDur(b)) * 0.9 < d) continue;
      const kind = mode === "blend" ? JUMP_BLEND.kind : (k % 2 === 0 ? "whip_left" : "whip_right");
      clips[j] = { ...b, transition_in: { kind, duration: d } };
      k++; count++;
    }
  }
  const timeline = withTracks(tl, (t, i) => (i === vi ? { ...t, clips } : t));
  return { timeline: sanitize(timeline), count };
}

// ---------------------------------------------------------------- cut stretches (edit by transcript)
const MUSIC_TAIL_FADE = 2;

/** Remove timeline stretches [a, b) from every track and close the gaps (ripple) — used by
 * edit-by-transcript and filler/retake removal. Music tracks aren't cut (the song keeps
 * playing); if the music now runs past the end of everything else it's trimmed there with
 * a fade-out. Clips cut in two become two clips; linked picture + sound stay linked. */
export function cutRanges(tl: Timeline, ranges: [number, number][]): OpResult {
  const merged: [number, number][] = [];
  for (const [a0, b0] of [...ranges].map(([a, b]) => [Math.max(0, Math.min(a, b)), Math.max(a, b)] as [number, number]).sort((x, y) => x[0] - y[0])) {
    if (b0 - a0 < 0.02) continue;
    const last = merged[merged.length - 1];
    if (last && a0 <= last[1] + 0.02) last[1] = Math.max(last[1], b0); else merged.push([a0, b0]);
  }
  if (!merged.length) return { error: "Nothing to cut" };
  const isMusic = (t: Track) => t.kind === "audio" && t.role === "music";
  // sound linked to picture is cut with it even on a music track (or the two would drift apart)
  const linked = new Set(tl.tracks.filter((t) => !isMusic(t)).flatMap((t) => t.clips.map((c) => c.link_id).filter(Boolean)));
  // a music track is left alone (the song keeps playing) unless something on it is linked to picture
  const freeTracks = new Set(tl.tracks.filter((t) => isMusic(t) && !t.clips.some((c) => c.link_id && linked.has(c.link_id))).map((t) => t.id));
  const free = (_c: Clip, t: Track) => freeTracks.has(t.id);
  for (const t of tl.tracks) {
    if (!t.locked) continue;
    if (t.clips.some((c) => !free(c, t) && merged.some(([a]) => clipEnd(c) > a + EPS))) return { error: `Track ${t.name} is locked` };
  }
  let cur = tl;
  for (let i = merged.length - 1; i >= 0; i--) {
    const [a, b] = merged[i];
    const relink = new Map<string, string>();
    const linkFor = (id?: string | null) => {
      if (!id) return id ?? null;
      if (!relink.has(id)) relink.set(id, newId());
      return relink.get(id)!;
    };
    // titles move with the picture; one that starts inside the cut starts where the cut was
    cur = { ...cur, titles: (cur.titles ?? []).map((t) => t.start >= b - EPS ? { ...t, start: round6(t.start - (b - a)) }
      : t.start > a ? { ...t, start: round6(a) } : t),
      blurs: (cur.blurs ?? []).map((x) => x.start >= b - EPS ? shiftBlur(x, -(b - a)) : x.start > a ? shiftBlur(x, a - x.start) : x) };
    cur = withTracks(cur, (track) => {
      const out: Clip[] = [];
      for (const c of track.clips) {
        if (free(c, track)) { out.push(c); continue; }
        const s = c.start, e = clipEnd(c);
        if (e <= a + EPS) { out.push(c); continue; }
        if (s >= b - EPS) { out.push({ ...c, start: round6(c.start - (b - a)) }); continue; }
        if (a - s >= MIN_CLIP + 0.01) out.push({ ...c, source_out: round6(c.source_in + (a - s) * c.speed), fade_out: 0 });
        if (e - b >= MIN_CLIP + 0.01) {
          const keepsId = a - s < MIN_CLIP + 0.01;  // nothing left before the cut: the piece after keeps the clip
          out.push({ ...c, id: keepsId ? c.id : newId(), link_id: keepsId ? c.link_id : linkFor(c.link_id), start: round6(a),
            source_in: round6(c.source_in + (b - s) * c.speed), transition_in: null, fade_in: 0 });
        }
      }
      return { ...track, clips: sortClips(out) };
    });
  }
  // music past the end of everything else: trim with a fade-out
  const end = Math.max(0, ...cur.tracks.flatMap((t) => t.clips.filter((c) => !free(c, t)).map(clipEnd)));
  cur = withTracks(cur, (track) => !isMusic(track) || end <= 0 ? track : {
    ...track,
    clips: track.clips.filter((c) => !free(c, track) || c.start < end - MIN_CLIP).map((c) => {
      if (!free(c, track) || clipEnd(c) <= end + EPS) return c;
      const d = end - c.start;
      return { ...c, source_out: round6(c.source_in + d * c.speed), fade_out: round6(Math.min(MUSIC_TAIL_FADE, d / 2)), fade_in: Math.min(c.fade_in ?? 0, d / 2) };
    }),
  });
  return { timeline: sanitize(cur) };
}

// ---------------------------------------------------------------- titles
export const TITLE_TEMPLATES: [TitleTemplate, string, Partial<Title>][] = [
  ["lower_third", "Lower third", { text: "Your name", subtext: "What you do", align: "left", duration: 5 }],
  ["big_title", "Big title", { text: "TITLE", subtext: "", align: "center", duration: 3 }],
  ["top_banner", "Top banner", { text: "Breaking news", subtext: "", align: "center", duration: 5 }],
  ["subscribe", "Subscribe", { text: "SUBSCRIBE", subtext: "", align: "right", duration: 4, accent: "#e62117" }],
  ["chapter", "Chapter card", { text: "Chapter title", subtext: "Part 1", align: "center", duration: 3 }],
];

export function addTitle(tl: Timeline, template: TitleTemplate, at: number): OpResult & { id?: string } {
  const preset = TITLE_TEMPLATES.find((x) => x[0] === template)?.[2] ?? {};
  const t: Title = { id: newId(), start: round6(Math.max(0, at)), duration: 4, template, text: "", subtext: "",
    color: "#ffffff", accent: "#ff5a3c", align: "left", size: 1, ...preset };
  return { timeline: { ...tl, titles: [...(tl.titles ?? []), t] }, id: t.id };
}

export function updateTitle(tl: Timeline, id: string, patch: Partial<Omit<Title, "id">>): OpResult {
  const t = (tl.titles ?? []).find((x) => x.id === id);
  if (!t) return { error: "Title not found" };
  const n: Title = { ...t, ...patch };
  n.start = round6(Math.max(0, n.start));
  n.duration = round6(Math.max(0.5, Math.min(600, n.duration)));
  n.size = Math.max(0.5, Math.min(2, n.size));
  n.text = n.text.slice(0, 80); n.subtext = n.subtext.slice(0, 100);
  if (!/^#[0-9a-fA-F]{6}$/.test(n.color) || !/^#[0-9a-fA-F]{6}$/.test(n.accent)) return { error: "Colours must be like #ff5a3c" };
  return { timeline: { ...tl, titles: (tl.titles ?? []).map((x) => (x.id === id ? n : x)) } };
}

export function removeTitle(tl: Timeline, id: string): OpResult {
  return { timeline: { ...tl, titles: (tl.titles ?? []).filter((x) => x.id !== id) } };
}

// ---------------------------------------------------------------- privacy blur
export function shiftBlur(b: Blur, dt: number): Blur {
  const start = round6(Math.max(0, b.start + dt));
  const d = start - b.start;
  return { ...b, start, keys: b.keys.map((k) => ({ ...k, t: round6(Math.max(0, k.t + d)) })).filter((k, i, a) => i === 0 || k.t - a[i - 1].t >= 0.001) };
}

/** The blurred box at timeline time t (keys interpolated; held before the first / after the last). */
export function blurAt(b: Blur, t: number): BlurKey {
  const k = b.keys;
  if (t <= k[0].t || k.length === 1) return k[0];
  if (t >= k[k.length - 1].t) return k[k.length - 1];
  let i = 0;
  while (i + 1 < k.length && k[i + 1].t <= t) i++;
  const a = k[i], c = k[i + 1], f = (t - a.t) / (c.t - a.t);
  return { t, x: a.x + (c.x - a.x) * f, y: a.y + (c.y - a.y) * f, w: a.w + (c.w - a.w) * f, h: a.h + (c.h - a.h) * f };
}

const clampBox = (k: BlurKey): BlurKey => {
  const w = Math.max(0.01, Math.min(1, k.w)), h = Math.max(0.01, Math.min(1, k.h));
  return { t: round6(Math.max(0, k.t)), w: round6(w), h: round6(h), x: round6(Math.max(-0.5, Math.min(1, k.x))), y: round6(Math.max(-0.5, Math.min(1, k.y))) };
};

export function addBlur(tl: Timeline, at: number, box: Omit<BlurKey, "t">, duration = 3): OpResult & { id?: string } {
  const b: Blur = { id: newId(), start: round6(Math.max(0, at)), duration: Math.max(0.1, Math.min(3600, duration)), mode: "blur", shape: "rect",
    strength: 0.7, keys: [clampBox({ t: Math.max(0, at), ...box })] };
  return { timeline: { ...tl, blurs: [...(tl.blurs ?? []), b] }, id: b.id };
}

export function updateBlur(tl: Timeline, id: string, patch: Partial<Omit<Blur, "id">>): OpResult {
  const b = (tl.blurs ?? []).find((x) => x.id === id);
  if (!b) return { error: "Blur not found" };
  let n: Blur = { ...b, ...patch };
  if (patch.start !== undefined) n = shiftBlur({ ...n, start: b.start }, patch.start - b.start);
  n.duration = round6(Math.max(0.1, Math.min(3600, n.duration)));
  n.strength = Math.max(0.1, Math.min(1, n.strength));
  const keys = [...n.keys].map(clampBox).sort((x, y) => x.t - y.t).filter((k, i, a) => i === 0 || k.t - a[i - 1].t >= 0.001).slice(0, 2000);
  if (!keys.length) return { error: "A blur needs an area" };
  n.keys = keys;
  return { timeline: { ...tl, blurs: (tl.blurs ?? []).map((x) => (x.id === id ? n : x)) } };
}

export function removeBlur(tl: Timeline, id: string): OpResult {
  return { timeline: { ...tl, blurs: (tl.blurs ?? []).filter((x) => x.id !== id) } };
}

// ---------------------------------------------------------------- music beats
const isMusicTrack = (t: Track) => t.kind === "audio" && t.role === "music";

/** Beat times on the timeline: each music clip's beats (source seconds) placed where it plays. */
export function beatTimes(tl: Timeline, beatsByMedia: Record<string, number[]>): number[] {
  const out: number[] = [];
  for (const t of tl.tracks) {
    if (!isMusicTrack(t) || t.muted) continue;
    for (const c of t.clips) for (const b of beatsByMedia[c.media_id] ?? []) {
      if (b >= c.source_in && b < c.source_out) out.push(round6(c.start + (b - c.source_in) / c.speed));
    }
  }
  return out.sort((a, b) => a - b);
}

/** Move each cut between back-to-back V1 clips onto the nearest beat (within ``tolerance`` s)
 * with a roll edit: the clip before gets longer/shorter and the one after starts
 * earlier/later by the same amount, so nothing else moves. Linked sound moves with the
 * picture. Cuts without room in the footage are left alone. */
export function snapCutsToBeats(tl: Timeline, beats: number[], media: MediaMap, tolerance = 0.25): OpResult & { count?: number; skipped?: number } {
  const vi = tl.tracks.findIndex((t) => t.kind === "video");
  if (vi < 0 || !beats.length) return { error: "No beats to snap to — find the beat of your music first" };
  const v = [...tl.tracks[vi].clips].sort((a, b) => a.start - b.start);
  const changes = new Map<string, Partial<Clip>>();   // by link group (or clip id)
  let count = 0, skipped = 0;
  const groupOf = (c: Clip) => tl.tracks.flatMap((t) => t.clips.filter((x) => x.id === c.id || (c.link_id && x.link_id === c.link_id)).map((x) => ({ x, t })));
  for (let i = 0; i + 1 < v.length; i++) {
    const a = v[i], b = v[i + 1];
    const cut = clipEnd(a);
    if (Math.abs(b.start - cut) > 0.02) continue;
    let near = beats[0];
    for (const t of beats) if (Math.abs(t - cut) < Math.abs(near - cut)) near = t;
    const d = near - cut;
    if (Math.abs(d) < 0.01 || Math.abs(d) > tolerance) continue;
    const ga = groupOf(a), gb = groupOf(b);
    const eff = (x: Clip) => ({ ...x, ...(changes.get(x.id) ?? {}) });   // with earlier snaps applied
    const okA = ga.every(({ x }) => { const e = eff(x), so = e.source_out + d * e.speed; return so <= (media[x.media_id]?.duration ?? 0) + 1e-6 && (so - e.source_in) / e.speed >= MIN_CLIP + 0.05; });
    const okB = gb.every(({ x }) => { const e = eff(x), si = e.source_in + d * e.speed; return si >= -1e-6 && (e.source_out - si) / e.speed >= MIN_CLIP + 0.05; });
    const locked = [...ga, ...gb].some(({ t }) => t.locked);
    if (!okA || !okB || locked) { skipped++; continue; }
    for (const { x } of ga) { const e = eff(x); changes.set(x.id, { ...(changes.get(x.id) ?? {}), source_out: round6(e.source_out + d * e.speed) }); }
    for (const { x } of gb) { const e = eff(x); changes.set(x.id, { ...(changes.get(x.id) ?? {}), source_in: round6(e.source_in + d * e.speed), start: round6(e.start + d) }); }
    v[i + 1] = { ...b, start: b.start + d, source_in: b.source_in + d * b.speed };  // later cuts see the new position
    count++;
  }
  if (!count) return skipped ? { error: `No cut could move onto a beat (${skipped} had no spare footage)` } : { error: "No cuts are close to a beat" };
  const timeline = withTracks(tl, (t) => ({ ...t, clips: sortClips(t.clips.map((c) => (changes.has(c.id) ? { ...c, ...changes.get(c.id) } : c))) }));
  // a roll must never make neighbours overlap on any track
  for (const t of timeline.tracks) {
    const cs = [...t.clips].sort((x, y) => x.start - y.start);
    for (let i = 0; i + 1 < cs.length; i++) if (clipEnd(cs[i]) > cs[i + 1].start + 1e-4) return { error: `Snapping would overlap clips on ${t.name}` };
  }
  return { timeline: sanitize(timeline), count, skipped };
}

/** Trim music that runs past the end of the video, with a fade-out (and fade in at its start if none). */
export function fitMusicToVideo(tl: Timeline, fade = 2): OpResult {
  const end = Math.max(0, ...tl.tracks.filter((t) => !isMusicTrack(t)).flatMap((t) => t.clips.map(clipEnd)));
  if (end <= 0) return { error: "Put your video on the timeline first" };
  let changed = false;
  const timeline = withTracks(tl, (t) => {
    if (!isMusicTrack(t)) return t;
    const clips = t.clips.filter((c) => c.start < end - MIN_CLIP).map((c) => {
      if (clipEnd(c) <= end + EPS) return c;
      changed = true;
      const d = end - c.start;
      return { ...c, source_out: round6(c.source_in + d * c.speed), fade_out: round6(Math.min(fade, d / 2)), fade_in: Math.min(c.fade_in ?? 0, d / 2) };
    });
    if (clips.length !== t.clips.length) changed = true;
    return { ...t, clips };
  });
  return changed ? { timeline: sanitize(timeline) } : { error: "The music already ends with the video" };
}

// ---------------------------------------------------------------- transition preview
export interface TransitionState { a: Clip; b: Clip; kind: string; p: number; aTime: number; bTime: number }

/** The transition playing at timeline time t on a track (same timing as the export:
 *  centred on the cut, half from each clip; the outgoing clip runs past its out-point). */
export function transitionAt(track: Track, t: number): TransitionState | null {
  for (const b of track.clips) {
    if (!b.transition_in) continue;
    const h = b.transition_in.duration / 2;
    if (t < b.start - h || t >= b.start + h) continue;
    const a = track.clips.find((x) => x.id !== b.id && Math.abs(clipEnd(x) - b.start) < 0.02);
    if (!a) return null;  // nothing before it: the export fades up from black instead
    return {
      a, b, kind: b.transition_in.kind, p: Math.max(0, Math.min(1, (t - (b.start - h)) / (2 * h))),
      aTime: a.source_out + (t - b.start) * a.speed,
      bTime: Math.max(0, b.source_in + (t - b.start) * b.speed),
    };
  }
  return null;
}
