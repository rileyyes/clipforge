// Pure, immutable timeline operations. Every edit in the UI goes through here,
// so these functions ARE the editing engine (and are unit-tested in ops.test.ts).
// Each returns { timeline } on success or { error } without changing anything.

import type { Clip, KfProp, Keyframe, MediaAsset, MediaMap, Timeline, Track, TrackKind } from "./types";
import { KF_LIMITS } from "./keyframes";

export const MIN_CLIP = 0.04; // seconds; matches backend MIN_CLIP_DURATION
const EPS = 1e-6;

export type OpResult = { timeline: Timeline; error?: undefined; created?: string[] } | { error: string; timeline?: undefined };

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
  return {
    timeline: withTracks(removed, (track) => ({
      ...track,
      clips: track.clips.map((c) => {
        const sh = shiftAt(c.start);
        return sh > EPS ? { ...c, start: round6(Math.max(0, c.start - sh)) } : c;
      }),
    })),
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
