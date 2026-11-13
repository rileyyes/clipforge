// Pure, immutable timeline operations. Every edit in the UI goes through here,
// so these functions ARE the editing engine (and are unit-tested in ops.test.ts).
// Each returns { timeline } on success or { error } without changing anything.

import { BLEND_MODES, type BlendMode } from "./types";
import type { Clip, Crop, KfProp, Keyframe, MediaAsset, MediaMap, Marker, Timeline, Title, TitleTemplate, Track, TrackKind, Blur, BlurKey } from "./types";
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

export function overlaps(track: Track, start: number, end: number, ignore: Set<string>): boolean {
  return track.clips.some((c) => !ignore.has(c.id) && start < clipEnd(c) - EPS && end > c.start + EPS);
}

export function sortClips(clips: Clip[]): Clip[] {
  return [...clips].sort((a, b) => a.start - b.start);
}

export function withTracks(tl: Timeline, map: (t: Track, i: number) => Track): Timeline {
  return { ...tl, tracks: tl.tracks.map(map) };
}

export function lockedError(refs: ClipRef[]): string | null {
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
  const after = withTracks(tl, (track) => {
    let clips = track.clips.filter((c) => !(c.id === id && track.id !== target.id));
    clips = clips.map((c) => moved.get(c.id) ?? c);
    if (track.id === target.id && track.id !== primary.track.id) clips.push(moved.get(id)!);
    return { ...track, clips: sortClips(clips) };
  });
  return { timeline: carryWithClips(tl, after) };
}

/** Move several clips (each with its linked clips) by the same `delta` seconds,
 *  keeping their spacing. They stay on their tracks. If the earliest would go
 *  before 0, the whole group stops at 0. Rejects overlaps and locked tracks. */
export function moveClips(tl: Timeline, ids: string[], delta: number): OpResult {
  const all = expandLinked(tl, ids);
  if (!all.size) return { error: "Nothing selected" };
  const refs = [...all].map((i) => findClip(tl, i)!);
  const le = lockedError(refs);
  if (le) return { error: le };
  const minStart = Math.min(...refs.map((r) => r.clip.start));
  if (minStart + delta < 0) delta = -minStart;
  if (Math.abs(delta) < EPS) return { timeline: tl };
  for (const r of refs) {
    const s = r.clip.start + delta;
    if (overlaps(r.track, s, s + clipDuration(r.clip), all)) return { error: `Clips can't overlap on ${r.track.name}` };
  }
  const after = withTracks(tl, (track) =>
    track.clips.some((c) => all.has(c.id))
      ? { ...track, clips: sortClips(track.clips.map((c) => (all.has(c.id) ? { ...c, start: round6(c.start + delta) } : c))) }
      : track);
  return { timeline: carryWithClips(tl, after) };
}

// ---------------------------------------------------------------- overlays follow moved clips

/** The clip a title or marker belongs to: the lowest visible video track with a clip at t
 *  (your main picture; moving a face cam or B-roll on V2 doesn't drag titles along). */
function baseClipAt(tl: Timeline, t: number): Clip | null {
  for (const tr of tl.tracks) if (tr.kind === "video" && !tr.hidden) { const c = clipAt(tr, t); if (c) return c; }
  return null;
}

/** After clips were moved (same ids, new starts), move each title, marker and blur that sat
 *  on a moved clip by the same amount, so it stays on the same moment of the footage.
 *  Titles and markers follow the main picture (see baseClipAt); a blur follows the picture
 *  it covers (the top one). Items over nothing, or over a clip that didn't move, stay. */
export function carryWithClips(before: Timeline, after: Timeline): Timeline {
  const starts = new Map<string, number>();
  for (const tr of after.tracks) for (const c of tr.clips) starts.set(c.id, c.start);
  const shiftOf = (c: Clip | null) => {
    if (!c) return 0;
    const now = starts.get(c.id);
    return now === undefined || Math.abs(now - c.start) < EPS ? 0 : now - c.start;
  };
  const probe = (t: number) => t + 1e-4;  // the clip that starts at t, not the one ending there
  let changed = false;
  const titles = (after.titles ?? []).map((x) => {
    const d = shiftOf(baseClipAt(before, probe(x.start)));
    if (!d) return x;
    changed = true;
    return { ...x, start: round6(Math.max(0, x.start + d)) };
  });
  const markers = (after.markers ?? []).map((m) => {
    const d = shiftOf(baseClipAt(before, probe(m.t)));
    if (!d) return m;
    changed = true;
    return { ...m, t: round6(Math.max(0, m.t + d)) };
  }).sort((a, b) => a.t - b.t);
  const blurs = (after.blurs ?? []).map((b) => {
    const d = shiftOf(topVideoClipAt(before, probe(b.start))?.clip ?? null);
    if (!d) return b;
    changed = true;
    return shiftBlur(b, d);
  });
  if (!changed) return after;
  return {
    ...after,
    ...(after.titles ? { titles } : {}),
    ...(after.markers ? { markers } : {}),
    ...(after.blurs ? { blurs } : {}),
  };
}

// ---------------------------------------------------------------- link / unlink

/** Unlink picture and sound: each selected clip (and the clips linked to it) can then be
 *  moved, trimmed and deleted on its own. */
export function unlinkClips(tl: Timeline, ids: string[]): OpResult {
  const all = expandLinked(tl, ids);
  const refs = [...all].map((i) => findClip(tl, i)!).filter(Boolean);
  if (!refs.some((r) => r.clip.link_id)) return { error: "These clips aren't linked" };
  const le = lockedError(refs);
  if (le) return { error: le };
  return { timeline: withTracks(tl, (track) => track.clips.some((c) => all.has(c.id))
    ? { ...track, clips: track.clips.map((c) => (all.has(c.id) ? { ...c, link_id: null } : c)) } : track) };
}

/** Link the selected clips (and anything already linked to them) so they move, trim,
 *  split and delete together. They must be on different tracks and line up exactly (same
 *  start, length and speed): linked clips always stay in sync. Clip edges snap to each
 *  other, so drag/trim them into line first. */
export function linkClips(tl: Timeline, ids: string[]): OpResult {
  const all = expandLinked(tl, ids);
  const refs = [...all].map((i) => findClip(tl, i)!).filter(Boolean);
  if (refs.length < 2) return { error: "Select at least two clips to link (for example a video clip and a sound clip)" };
  const tracks = new Set(refs.map((r) => r.track.id));
  if (tracks.size !== refs.length) return { error: "Only one clip per track can be linked together" };
  const le = lockedError(refs);
  if (le) return { error: le };
  if (new Set(refs.map((r) => r.clip.link_id)).size === 1 && refs[0].clip.link_id) return { error: "These clips are already linked" };
  const r0 = refs[0].clip;
  if (refs.some((r) => Math.abs(r.clip.start - r0.start) > 1e-4 || Math.abs(clipDuration(r.clip) - clipDuration(r0)) > 1e-4 || r.clip.speed !== r0.speed))
    return { error: "Linked clips must start and end together: drag or trim them into line first (edges snap to each other)" };
  // two pieces of the same recording only link if they're the same moment of it (else picture and sound wouldn't match)
  if (refs.some((r) => refs.some((q) => q.clip.media_id === r.clip.media_id && Math.abs(q.clip.source_in - r.clip.source_in) > 1e-4)))
    return { error: "These are different moments of the same recording, so the picture and sound wouldn't match" };
  const link = newId();
  return { timeline: withTracks(tl, (track) => track.clips.some((c) => all.has(c.id))
    ? { ...track, clips: track.clips.map((c) => (all.has(c.id) ? { ...c, link_id: link } : c)) } : track) };
}

// ---------------------------------------------------------------- markers
export const MARKER_LIMIT = 500;

/** Add a marker at time t (at most one per 0.05 s). */
export function addMarker(tl: Timeline, t: number, color = "#ffb703"): OpResult & { id?: string } {
  const at = round6(Math.max(0, t));
  const ms = tl.markers ?? [];
  if (ms.some((m) => Math.abs(m.t - at) < 0.05)) return { error: "There's already a marker here" };
  if (ms.length >= MARKER_LIMIT) return { error: `At most ${MARKER_LIMIT} markers` };
  const m: Marker = { id: newId(), t: at, label: "", color };
  return { timeline: { ...tl, markers: [...ms, m].sort((a, b) => a.t - b.t) }, id: m.id };
}

export function updateMarker(tl: Timeline, id: string, patch: Partial<Omit<Marker, "id">>): OpResult {
  const m = (tl.markers ?? []).find((x) => x.id === id);
  if (!m) return { error: "Marker not found" };
  const n: Marker = { ...m, ...patch };
  n.t = round6(Math.max(0, n.t));
  n.label = n.label.slice(0, 100);
  if (!/^#[0-9a-fA-F]{6}$/.test(n.color)) return { error: "Colours must be like #ffb703" };
  return { timeline: { ...tl, markers: (tl.markers ?? []).map((x) => (x.id === id ? n : x)).sort((a, b) => a.t - b.t) } };
}

export function removeMarker(tl: Timeline, id: string): OpResult {
  if (!(tl.markers ?? []).some((x) => x.id === id)) return { error: "Marker not found" };
  return { timeline: { ...tl, markers: (tl.markers ?? []).filter((x) => x.id !== id) } };
}

/** The next (dir 1) or previous (dir -1) marker strictly after / before t, or null. */
export function markerNear(tl: Timeline, t: number, dir: 1 | -1): Marker | null {
  const ms = [...(tl.markers ?? [])].sort((a, b) => a.t - b.t);
  return dir > 0 ? ms.find((m) => m.t > t + 1e-3) ?? null : [...ms].reverse().find((m) => m.t < t - 1e-3) ?? null;
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
      ...(removed.markers ? { markers: removed.markers.map((m) => ({ ...m, t: newTime(m.t) })) } : {}),
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
  /** green screen (null turns it off) */
  chroma?: Clip["chroma"];
  /** Phase 20 blend mode (pictures only) */
  blend?: BlendMode;
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
  if (patch.chroma && (!/^#[0-9a-fA-F]{6}$/.test(patch.chroma.color) || !(patch.chroma.similarity >= 0.01 && patch.chroma.similarity <= 0.8)
    || !(patch.chroma.blend >= 0 && patch.chroma.blend <= 0.5))) return { error: "Green screen value out of range" };
  if (patch.chroma && ref.track.kind !== "video") return { error: "Green screen is for video clips" };
  if (patch.blend !== undefined && !(BLEND_MODES as readonly string[]).includes(patch.blend)) return { error: "Unknown blend mode" };
  if (patch.blend !== undefined && ref.track.kind !== "video") return { error: "Blend modes are for pictures" };
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
        if (patch.chroma !== undefined) u.chroma = patch.chroma;
        if (patch.blend !== undefined) u.blend = patch.blend;
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

export function setTrackRole(tl: Timeline, id: string, role: "dialogue" | "music" | "narration"): OpResult {
  return { timeline: withTracks(tl, (t) => (t.id === id && t.kind === "audio" ? { ...t, role } : t)) };
}

/** Name tag for an audio track (Phase 18): shown while it's talking, when name tags are on. */
export function setTrackTag(tl: Timeline, id: string, tag: string, color?: string): OpResult {
  if (color !== undefined && !/^#[0-9a-fA-F]{6}$/.test(color)) return { error: "Colours must be like #5865f2" };
  return { timeline: withTracks(tl, (t) => (t.id === id && t.kind === "audio"
    ? { ...t, tag: tag.slice(0, 24), ...(color !== undefined ? { tag_color: color } : {}) } : t)) };
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
      blurs: (cur.blurs ?? []).map((x) => x.start >= b - EPS ? shiftBlur(x, -(b - a)) : x.start > a ? shiftBlur(x, a - x.start) : x),
      ...(cur.markers ? { markers: cur.markers.map((m) => m.t >= b - EPS ? { ...m, t: round6(m.t - (b - a)) } : m.t > a ? { ...m, t: round6(a) } : m) } : {}) };
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
  ["pop_text", "Pop-up words", { text: "NO WAY!", x: 0.5, y: 0.3, rotation: -6, anim: "pop", duration: 2.5, color: "#ffffff" }],
  ["arrow", "Arrow", { text: "", x: 0.4, y: 0.5, rotation: 30, anim: "pop", duration: 3, accent: "#ff3b30" }],
  ["circle", "Circle", { text: "", x: 0.5, y: 0.5, rotation: 0, anim: "pop", duration: 3, accent: "#ff3b30" }],
  ["box", "Box", { text: "", x: 0.5, y: 0.5, rotation: 0, anim: "pop", duration: 3, accent: "#ffde00" }],
  // Phase 18
  ["sticker", "Emoji sticker", { text: "😂", x: 0.75, y: 0.3, rotation: -8, anim: "pop", duration: 2.5, color: "#ffde00" }],
  ["count_card", "Callout card", { text: "Name", subtext: "Detail", duration: 4, accent: "#e3242b" }],
  ["number_card", "Number card", { text: "Your pick", subtext: "", number: 10, duration: 3, accent: "#ffde00" }],
  ["tally", "List screen", { text: "THE LIST", subtext: "", duration: 8, accent: "#e3242b" }],
  // Phase 19
  ["ticker", "Timer", { text: "TIME LEFT", count_from: 10, count_to: 0, format: "time", duration: 10.3, x: 0.85, y: 0.16, anim: "none", accent: "#ff3b30" }],
  ["ticker", "Money ticker", { text: "", count_from: 0, count_to: 10000, format: "money", duration: 3, x: 0.5, y: 0.3, anim: "pop", accent: "#2bb38a", color: "#2bb38a" }],
  ["stamp", "Time & place", { text: "DAY 1", subtext: "6:00 AM", duration: 4, accent: "#ffde00" }],
  ["route", "Route on a map", { text: "", points: [[0.25, 0.7], [0.45, 0.45], [0.7, 0.55]], duration: 5, accent: "#ff3b30" }],
  ["highlight", "Highlighter", { text: "", x: 0.5, y: 0.5, w: 0.4, h: 0.08, duration: 3, accent: "#ffde00" }],
];

/** Kept so older projects still show and export them, but no longer offered as new titles (removed at the owner's request). */
export const RETIRED_TEMPLATES: string[] = ["count_card", "tally"];

export function addTitle(tl: Timeline, template: TitleTemplate, at: number, label?: string): OpResult & { id?: string } {
  const preset = (label ? TITLE_TEMPLATES.find((x) => x[0] === template && x[1] === label) : undefined)?.[2]
    ?? TITLE_TEMPLATES.find((x) => x[0] === template)?.[2] ?? {};
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
  if ([n.stroke_color, n.glow_color].some((c) => c !== undefined && !/^#[0-9a-fA-F]{6}$/.test(c))) return { error: "Colours must be like #ff5a3c" };
  if (n.stroke != null) n.stroke = Math.max(0, Math.min(24, n.stroke));
  if (n.shadow != null) n.shadow = Math.max(0, Math.min(24, n.shadow));
  if (n.glow != null) n.glow = Math.max(0, Math.min(40, n.glow));
  if (n.number != null) n.number = Math.max(0, Math.min(999, Math.round(n.number)));
  if (n.count_from != null) n.count_from = Math.max(-1e9, Math.min(1e9, n.count_from));
  if (n.count_to != null) n.count_to = Math.max(-1e9, Math.min(1e9, n.count_to));
  if (n.points) n.points = n.points.slice(0, 20).map(([x, y]) => [round6(Math.max(0, Math.min(1, x))), round6(Math.max(0, Math.min(1, y)))]);
  if (n.w != null) n.w = Math.max(0.01, Math.min(1, n.w));
  if (n.h != null) n.h = Math.max(0.01, Math.min(1, n.h));
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
export const isMusicTrack = (t: Track) => t.kind === "audio" && t.role === "music";

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

// ---------------------------------------------------------------- background music (Phase 14)
export interface MusicOptions {
  volume: number;        // 0..2 (1 = as recorded); ducking lowers it further under speech
  fadeIn: number;        // s, at the start
  fadeOut: number;       // s, at the end
  songStart: number;     // s into the song to begin (skip an intro); loops restart here too
  loop: boolean;         // repeat the song if it's shorter than the stretch
  /** Phase 16: overlap each loop with the next by this many seconds (rounded to whole beats
   *  when `beats` is given) on a second music track, instead of a dip. 0 = the old dip. */
  crossfade?: number;
  /** the song's beat times (seconds): loops then start on a beat and last whole bars */
  beats?: number[];
}
export const MUSIC_DEFAULTS: MusicOptions = { volume: 0.3, fadeIn: 1, fadeOut: 2, songStart: 0, loop: true };
/** fade at each loop join (out and back in), so the jump back isn't a click */
export const LOOP_JOIN_FADE = 0.3;

/** End of the video part of the edit (everything except music tracks). */
export function videoEnd(tl: Timeline): number {
  return Math.max(0, ...tl.tracks.filter((t) => !isMusicTrack(t)).flatMap((t) => t.clips.map(clipEnd)));
}

/** Put a song under the video from `from` to `to` (timeline seconds), looping it if it's
 *  shorter, on a music track (one that's free there, else a new "Music" track). Music
 *  tracks are lowered under speech when ducking is on. */
export function addMusic(tl: Timeline, media: MediaAsset, from: number, to: number, o: MusicOptions = MUSIC_DEFAULTS): OpResult {
  if (o.loop && (o.crossfade ?? 0) > 0) {
    const r = addMusicCrossfaded(tl, media, from, to, o);
    if (r) return r;      // null: the song is too short for a crossfaded loop; fall back to the dip
  }
  if (!media.has_audio) return { error: `“${media.original_name}” has no sound` };
  from = round6(Math.max(0, from)); to = round6(to);
  if (!(to - from >= 0.5)) return { error: "Pick an end time at least half a second after the start" };
  const songStart = Math.max(0, o.songStart);
  const songLen = media.duration - songStart;
  if (songLen < 0.5) return { error: "“Start song at” is past the end of the song" };
  if (!(o.volume >= 0 && o.volume <= 2)) return { error: "Volume must be between 0 and 200 %" };
  // pieces
  const pieces: [number, number, number][] = []; // [start, source_in, length]
  for (let t = from; to - t > MIN_CLIP - EPS;) {
    const len = Math.min(to - t, songLen);
    pieces.push([t, songStart, len]);
    t = round6(t + len);
    if (!o.loop) break;
    if (pieces.length > 200) return { error: "That song is too short to loop over such a long stretch" };
  }
  if (pieces.length > 1 && pieces[pieces.length - 1][2] < MIN_CLIP) pieces.pop();
  // a music track that's free over [from, end)
  const end = pieces.length ? pieces[pieces.length - 1][0] + pieces[pieces.length - 1][2] : to;
  let target = tl.tracks.find((t) => isMusicTrack(t) && !t.locked && !t.clips.some((c) => c.start < end - EPS && clipEnd(c) > from + EPS));
  let base = tl;
  if (!target) {
    if (tl.tracks.length >= 32) return { error: "Track limit reached" };
    const n = tl.tracks.filter(isMusicTrack).length;
    target = { id: newId(), kind: "audio", name: n ? `Music ${n + 1}` : "Music", muted: false, hidden: false, locked: false, clips: [], role: "music" };
    base = { ...tl, tracks: [...tl.tracks, target] };
  }
  const created: string[] = [];
  const clips: Clip[] = pieces.map(([start, si, len], i) => {
    const first = i === 0, last = i === pieces.length - 1;
    const half = len / 2;
    const c: Clip = {
      id: newId(), media_id: media.id, start: round6(start), source_in: round6(si), source_out: round6(si + len), speed: 1,
      volume: round6(o.volume), transform: { x: 0, y: 0, scale: 1, rotation: 0 }, link_id: null, label: null,
      fade_in: round6(Math.min(half, first ? Math.max(0, o.fadeIn) : LOOP_JOIN_FADE)),
      fade_out: round6(Math.min(half, last ? Math.max(0, o.fadeOut) : LOOP_JOIN_FADE)),
    };
    created.push(c.id);
    return c;
  });
  return {
    timeline: withTracks(base, (t) => (t.id === target!.id ? { ...t, clips: sortClips([...t.clips, ...clips]) } : t)),
    created,
  };
}

/** Music on the timeline as the user thinks of it: back-to-back pieces of the same song
 *  on the same track (a loop) form one item. */
export interface MusicItem { track: Track; clips: Clip[]; media_id: string; start: number; end: number; volume: number }
export function musicItems(tl: Timeline): MusicItem[] {
  const out: MusicItem[] = [];
  const loops = new Map<string, MusicItem>();   // crossfaded loops (label "♪ …"), across two tracks
  for (const t of tl.tracks.filter(isMusicTrack)) for (const c of t.clips) {
    if (!c.label?.startsWith("♪ ")) continue;
    const it = loops.get(c.label);
    if (it) { it.clips.push(c); it.start = Math.min(it.start, c.start); it.end = Math.max(it.end, clipEnd(c)); }
    else loops.set(c.label, { track: t, clips: [c], media_id: c.media_id, start: c.start, end: clipEnd(c), volume: c.volume });
  }
  for (const t of tl.tracks.filter(isMusicTrack)) {
    for (const c of [...t.clips].sort((a, b) => a.start - b.start)) {
      if (c.label?.startsWith("♪ ")) continue;
      const last = out[out.length - 1];
      if (last && last.track.id === t.id && last.media_id === c.media_id && Math.abs(last.end - c.start) < 1e-3) {
        last.clips.push(c); last.end = clipEnd(c);
      } else out.push({ track: t, clips: [c], media_id: c.media_id, start: c.start, end: clipEnd(c), volume: c.volume });
    }
  }
  for (const it of loops.values()) it.clips.sort((a, b) => a.start - b.start);
  return [...out, ...loops.values()].sort((a, b) => a.start - b.start);
}

/** Change the volume of every piece of a music item. */
export function setMusicVolume(tl: Timeline, ids: string[], volume: number): OpResult {
  const v = round6(Math.min(2, Math.max(0, volume)));
  const set = new Set(ids);
  const refs = ids.map((i) => findClip(tl, i)).filter(Boolean) as ClipRef[];
  const le = lockedError(refs);
  if (le) return { error: le };
  return { timeline: withTracks(tl, (t) => t.clips.some((c) => set.has(c.id)) ? { ...t, clips: t.clips.map((c) => (set.has(c.id) ? { ...c, volume: v } : c)) } : t) };
}

/** Beat-aligned loop with real crossfades: the loop runs from the first beat at or after
 *  "start song at" for a whole number of bars (4 beats), and each repeat starts `xf` before the
 *  previous one ends, alternating between two music tracks, so they fade into each other.
 *  Pieces of one stretch share a label ("♪ name #id") so they're listed as one song. */
function addMusicCrossfaded(tl: Timeline, media: MediaAsset, from: number, to: number, o: MusicOptions): OpResult | null {
  if (!media.has_audio) return { error: `“${media.original_name}” has no sound` };
  from = round6(Math.max(0, from)); to = round6(to);
  if (!(to - from >= 0.5)) return { error: "Pick an end time at least half a second after the start" };
  if (!(o.volume >= 0 && o.volume <= 2)) return { error: "Volume must be between 0 and 200 %" };
  const beats = (o.beats ?? []).filter((b) => b >= 0 && b < media.duration - 0.05);
  let s0 = Math.max(0, o.songStart), s1 = media.duration - 0.05, xf = o.crossfade!;
  if (beats.length >= 9) {
    const period = beats.slice(1).map((b, i) => b - beats[i]).sort((a, b) => a - b)[Math.floor((beats.length - 1) / 2)];
    const k0 = beats.findIndex((b) => b >= s0 - 0.02);
    if (k0 >= 0) {
      s0 = beats[k0];
      let k1 = beats.length - 1;
      while (k1 > k0 && (k1 - k0) % 4 !== 0) k1--;
      if (k1 - k0 >= 8) s1 = beats[k1];
      xf = Math.max(period, Math.round(xf / period) * period);
    }
  }
  const loopLen = s1 - s0;
  if (to - from <= loopLen + 1e-6) return null;                // no loop needed
  if (loopLen < 2 * xf + 1) return null;
  // two music tracks free over the whole stretch
  const free = (t: Track) => isMusicTrack(t) && !t.locked && !t.clips.some((c) => c.start < to - EPS && clipEnd(c) > from + EPS);
  let base = tl;
  const ids: string[] = [];
  for (const t of base.tracks) if (free(t) && ids.length < 2) ids.push(t.id);
  while (ids.length < 2) {
    if (base.tracks.length >= 32) return { error: "Track limit reached" };
    const n = base.tracks.filter(isMusicTrack).length;
    const t: Track = { id: newId(), kind: "audio", name: n ? `Music ${n + 1}` : "Music", muted: false, hidden: false, locked: false, clips: [], role: "music" };
    base = { ...base, tracks: [...base.tracks, t] };
    ids.push(t.id);
  }
  const label = `♪ ${media.original_name.slice(0, 60)} #${newId().slice(0, 4)}`;
  const pieces: Clip[][] = [[], []];
  const created: string[] = [];
  let t = from, i = 0;
  while (to - t > MIN_CLIP - EPS) {
    const len = Math.min(to - t, loopLen);
    const last = t + len >= to - EPS;
    const c: Clip = { id: newId(), media_id: media.id, start: round6(t), source_in: round6(s0), source_out: round6(s0 + len), speed: 1,
      volume: round6(o.volume), transform: { x: 0, y: 0, scale: 1, rotation: 0 }, link_id: null, label,
      fade_in: round6(Math.min(len / 2, i === 0 ? Math.max(0, o.fadeIn) : xf)),
      fade_out: round6(Math.min(len / 2, last ? Math.max(0, o.fadeOut) : xf)) } as Clip;
    pieces[i % 2].push(c);
    created.push(c.id);
    if (last) break;
    t = round6(t + loopLen - xf);
    if (++i > 400) return { error: "That song is too short to loop over such a long stretch" };
  }
  return {
    timeline: withTracks(base, (tr) => (tr.id === ids[0] ? { ...tr, clips: sortClips([...tr.clips, ...pieces[0]]) }
      : tr.id === ids[1] ? { ...tr, clips: sortClips([...tr.clips, ...pieces[1]]) } : tr)),
    created,
  };
}

