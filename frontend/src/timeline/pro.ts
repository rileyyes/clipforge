// Phase 15: freeze frame, reverse, speed ramps, split-screen / picture-in-picture layouts.
import {
  clipDuration, clipEnd, findClip, isMusicTrack, linkedGroup, lockedError, MIN_CLIP, newId, round6, shiftBlur,
  sortClips, splitAt, topVideoClipAt, withTracks, type OpResult,
} from "./ops";
import type { Clip, MediaAsset, Timeline, Transform } from "./types";

const EPS = 1e-6;

/** Push everything that starts at or after `at` later by `delta` seconds (all tracks
 *  except music, which keeps playing; titles, blurs and markers too). */
export function rippleInsert(tl: Timeline, at: number, delta: number): Timeline {
  const shift = (t: number) => (t >= at - EPS ? round6(t + delta) : t);
  // clips that move: everything from `at` on, except music (which keeps playing)... but a clip
  // linked to one that moves always moves with it, even on a music track
  const moving = new Set<string>(), links = new Set<string>();
  for (const t of tl.tracks) if (!isMusicTrack(t)) for (const c of t.clips) if (c.start >= at - EPS) { moving.add(c.id); if (c.link_id) links.add(c.link_id); }
  for (const t of tl.tracks) for (const c of t.clips) if (c.link_id && links.has(c.link_id)) moving.add(c.id);
  // a music track that has to move a linked clip moves everything after it too (no collisions)
  for (const t of tl.tracks) if (isMusicTrack(t) && t.clips.some((c) => moving.has(c.id))) for (const c of t.clips) if (c.start >= at - EPS) moving.add(c.id);
  return {
    ...withTracks(tl, (t) => ({ ...t, clips: t.clips.map((c) => (moving.has(c.id) ? { ...c, start: round6(c.start + delta) } : c)) })),
    ...(tl.titles ? { titles: tl.titles.map((x) => ({ ...x, start: shift(x.start) })) } : {}),
    ...(tl.blurs ? { blurs: tl.blurs.map((b) => (b.start >= at - EPS ? shiftBlur(b, delta) : b)) } : {}),
    // (closing a gap can move later markers in front of earlier ones: keep them in order)
    ...(tl.markers ? { markers: tl.markers.map((m) => ({ ...m, t: Math.max(0, shift(m.t)) })).sort((a, b) => a.t - b.t) } : {}),
  };
}

// ---------------------------------------------------------------- freeze frame
/** Where a freeze is taken from: the video clip at the playhead (top visible one if none is selected). */
export function freezeSource(tl: Timeline, at: number, selected: string[]): { clip: Clip; sourceT: number } | null {
  const pick = selected.map((id) => findClip(tl, id)).find((r) => r && r.track.kind === "video" && at >= r.clip.start - EPS && at <= clipEnd(r.clip) + EPS);
  const clip = pick?.clip ?? topVideoClipAt(tl, at)?.clip ?? null;
  if (!clip) return null;
  return { clip, sourceT: Math.min(clip.source_out - 0.001, clip.source_in + Math.max(0, at - clip.start) * clip.speed) };
}

/** Hold the picture at `at`: the clip is split there, everything after moves later by the
 *  freeze's length, and the freeze (a still clip, `freeze` media) goes in the gap. The sound
 *  pauses (music keeps playing). */
export function insertFreeze(tl: Timeline, clipId: string, at: number, freeze: MediaAsset): OpResult {
  const ref = findClip(tl, clipId);
  if (!ref || ref.track.kind !== "video") return { error: "Pick a video clip" };
  const le = lockedError(linkedGroup(tl, clipId));
  if (le) return { error: le };
  let t = tl;
  // too close to an edge to split: freeze right at that edge
  if (at <= ref.clip.start + MIN_CLIP) at = ref.clip.start;
  else if (at >= clipEnd(ref.clip) - MIN_CLIP) at = clipEnd(ref.clip);
  if (at > ref.clip.start + MIN_CLIP && at < clipEnd(ref.clip) - MIN_CLIP) {
    const r = splitAt(t, [clipId], at);
    if (r.error) return r;
    t = r.timeline!;
  }
  const d = freeze.duration;
  t = rippleInsert(t, at, d);
  const still: Clip = {
    id: newId(), media_id: freeze.id, start: round6(at), source_in: 0, source_out: round6(d), speed: 1, volume: 1, link_id: null,
    label: null, transform: { ...ref.clip.transform }, ...(ref.clip.crop ? { crop: { ...ref.clip.crop } } : {}),
    ...(ref.clip.color ? { color: { ...ref.clip.color } } : {}), ...(ref.clip.chroma ? { chroma: { ...ref.clip.chroma } } : {}),
  } as Clip;
  const out = withTracks(t, (tr) => (tr.id === ref.track.id ? { ...tr, clips: sortClips([...tr.clips, still]) } : tr));
  const clash = out.tracks.find((tr) => tr.clips.some((c, i, a) => i > 0 && c.start < clipEnd(a[i - 1]) - 1e-4));
  if (clash) return { error: `Something on ${clash.name} is in the way of the freeze` };
  return { timeline: out, created: [still.id] };
}

// ---------------------------------------------------------------- reverse
export const REVERSE_MAX = 60;

/** Swap a clip (and its linked sound) for the reversed copy of the same part of the recording. */
export function useReversed(tl: Timeline, clipId: string, rev: MediaAsset): OpResult {
  const group = linkedGroup(tl, clipId);
  if (!group.length) return { error: "Clip not found" };
  const le = lockedError(group);
  if (le) return { error: le };
  const ids = new Set(group.filter((r) => r.track.kind === "video" || rev.has_audio).map((r) => r.clip.id));
  return {
    timeline: withTracks(tl, (tr) => ({
      ...tr,
      clips: tr.clips.map((c) => {
        if (!ids.has(c.id)) return c;
        const span = Math.min(rev.duration, c.source_out - c.source_in);
        return { ...c, media_id: rev.id, source_in: 0, source_out: round6(span), keyframes: {} };
      }),
    })),
  };
}

// ---------------------------------------------------------------- speed ramps
export interface RampOptions {
  target: number;   // speed in the middle: < 1 slow motion, > 1 speed-up
  hold: number;     // seconds of the recording played at `target`
  ramp: number;     // seconds of the recording used to ease in, and again to ease out
  steps: number;    // pieces per ease
}
export const RAMP_SLOWMO: RampOptions = { target: 0.35, hold: 1.0, ramp: 0.5, steps: 6 };
export const RAMP_SPEEDUP: RampOptions = { target: 3, hold: 3.0, ramp: 0.8, steps: 6 };

/** Smooth speed change starting at the playhead: the clip (and its linked sound) is cut into
 *  small pieces whose speed eases from the clip's speed to `target`, holds, and eases back.
 *  Everything after moves to make room (slow motion) or closes up (speed-up). */
export function speedRamp(tl: Timeline, clipId: string, at: number, o: RampOptions): OpResult {
  const ref = findClip(tl, clipId);
  if (!ref) return { error: "Select a clip first" };
  const c0 = ref.clip;
  if (!(o.target >= 0.25 && o.target <= 4)) return { error: "Speed must be between 0.25x and 4x" };
  if (at < c0.start - EPS || at > clipEnd(c0) + EPS) return { error: "Put the playhead on the selected clip" };
  const group = linkedGroup(tl, clipId);
  const le = lockedError(group);
  if (le) return { error: le };
  const s0 = c0.source_in + (at - c0.start) * c0.speed;
  const need = 2 * o.ramp + o.hold;
  if (s0 + need > c0.source_out - MIN_CLIP) return { error: `Needs ${need.toFixed(1)} s of the clip after the playhead; move the playhead earlier or use a shorter effect` };
  // the source pieces and their speeds (smoothstep ease)
  const base = c0.speed;
  const ease = (f: number) => f * f * (3 - 2 * f);
  const pieces: [number, number, number][] = []; // [src a, src b, speed]
  // fewer, longer pieces when they'd be too short to be clips (fast clips)
  const fastest = Math.max(base, o.target) * 1.05;
  const steps = Math.max(1, Math.min(o.steps, Math.floor(o.ramp / (MIN_CLIP * fastest))));
  if (o.ramp / steps / fastest < MIN_CLIP || o.hold / o.target < MIN_CLIP) return { error: "That speed change is too short for this clip's speed" };
  const step = o.ramp / steps;
  let s = s0;
  for (let i = 0; i < steps; i++) { pieces.push([s, s + step, base + (o.target - base) * ease((i + 0.5) / steps)]); s += step; }
  pieces.push([s, s + o.hold, o.target]); s += o.hold;
  for (let i = 0; i < steps; i++) { pieces.push([s, s + step, o.target + (base - o.target) * ease((i + 0.5) / steps)]); s += step; }
  const rampDur = pieces.reduce((sum, [a, b, sp]) => sum + (b - a) / sp, 0);
  const delta = rampDur - need / base;                       // how much longer (or shorter) the edit gets
  const rampStart = c0.start + (s0 - c0.source_in) / base;
  const rampEnd = rampStart + need / base;                   // old timeline end of the ramped part
  // everything after the ramp moves by delta (insert room first, so nothing overlaps)
  let t: Timeline = tl;
  const groupIds = new Set(group.map((r) => r.clip.id));
  // make the tail of each clip in the group its own clip, starting at rampEnd (tails linked together)
  const tailLink = group.length > 1 ? newId() : null;
  t = withTracks(t, (tr) => {
    if (!tr.clips.some((c) => groupIds.has(c.id))) return tr;
    const clips: Clip[] = [];
    for (const c of tr.clips) {
      if (!groupIds.has(c.id)) { clips.push(c); continue; }
      const head = { ...c, source_out: round6(s0) };
      if (s0 - c.source_in > MIN_CLIP * base) clips.push(head);
      const tail = { ...c, id: newId(), start: round6(rampEnd), source_in: round6(s0 + need), link_id: tailLink };
      if (tail.source_out - tail.source_in > MIN_CLIP * base) clips.push(tail);
    }
    return { ...tr, clips };
  });
  t = delta >= 0 ? rippleInsert(t, rampEnd - EPS * 10, delta) : closeUp(t, rampEnd, -delta);
  // the ramp pieces, on every track of the group, linked piece by piece
  const links = pieces.map(() => newId());
  let at2 = rampStart;
  const starts = pieces.map(([a, b, sp]) => { const st = at2; at2 += (b - a) / sp; return st; });
  t = withTracks(t, (tr) => {
    const mine = group.find((g) => g.track.id === tr.id);
    if (!mine) return tr;
    const add: Clip[] = pieces.map(([a, b, sp], i) => ({ ...mine.clip, id: newId(), start: round6(starts[i]), source_in: round6(a), source_out: round6(b),
      speed: round6(sp), link_id: group.length > 1 ? links[i] : null }));
    return { ...tr, clips: sortClips([...tr.clips, ...add]) };
  });
  const clash = t.tracks.find((tr) => sortClips(tr.clips).some((c, i, a) => i > 0 && c.start < clipEnd(a[i - 1]) - 1e-4));
  if (clash) return { error: `Something on ${clash.name} is in the way of the speed change` };
  return { timeline: t };
}

/** Pull everything that starts at or after `at` earlier by `delta` (speed-up made the edit shorter). */
function closeUp(tl: Timeline, at: number, delta: number): Timeline {
  return rippleInsert(tl, at - EPS * 10, -delta);
}

// ---------------------------------------------------------------- layouts
export type Layout = "side_by_side" | "top_bottom" | "pip" | "reset";
export type Corner = "tl" | "tr" | "bl" | "br";

/** Arrange the top two video clips at the playhead: side by side, one above the other, or
 *  the upper one small in a corner (picture-in-picture). Uses each clip's position, size and
 *  crop, so you can fine-tune afterwards in the Clip tab. */
export function applyLayout(tl: Timeline, at: number, W: number, H: number, layout: Layout, corner: Corner = "br", pipSize = 0.3): OpResult {
  const under = tl.tracks.map((tr, i) => ({ tr, i })).filter(({ tr }) => tr.kind === "video" && !tr.hidden)
    .map(({ tr, i }) => ({ i, c: tr.clips.find((c) => at >= c.start - EPS && at < clipEnd(c) - EPS) }))
    .filter((x): x is { i: number; c: Clip } => !!x.c)
    .sort((a, b) => b.i - a.i);                                  // higher tracks first
  if (layout !== "reset" && under.length < 2) return { error: "Put a second clip on a video track above this one (V2) at the playhead first" };
  if (!under.length) return { error: "No video at the playhead" };
  const [top, bottom] = [under[0].c, under[1]?.c];
  const zero = { left: 0, right: 0, top: 0, bottom: 0 };
  const set: Record<string, { transform: Transform; crop: typeof zero }> = {};
  const T = (c: Clip, x: number, y: number, scale: number) => ({ ...c.transform, x: round6(x), y: round6(y), scale, rotation: 0 });
  if (layout === "reset") {
    for (const { c } of under.slice(0, 2)) set[c.id] = { transform: T(c, 0, 0, 1), crop: zero };
  } else if (layout === "side_by_side") {
    set[bottom!.id] = { transform: T(bottom!, -W / 4, 0, 1), crop: { ...zero, left: 0.25, right: 0.25 } };
    set[top.id] = { transform: T(top, W / 4, 0, 1), crop: { ...zero, left: 0.25, right: 0.25 } };
  } else if (layout === "top_bottom") {
    set[bottom!.id] = { transform: T(bottom!, 0, -H / 4, 1), crop: { ...zero, top: 0.25, bottom: 0.25 } };
    set[top.id] = { transform: T(top, 0, H / 4, 1), crop: { ...zero, top: 0.25, bottom: 0.25 } };
  } else {
    const m = 0.03, s = Math.min(0.6, Math.max(0.15, pipSize));
    const x = (W / 2 - m * W - (s * W) / 2) * (corner.endsWith("r") ? 1 : -1);
    const y = (H / 2 - m * H - (s * H) / 2) * (corner.startsWith("b") ? 1 : -1);
    set[bottom!.id] = { transform: T(bottom!, 0, 0, 1), crop: zero };
    set[top.id] = { transform: T(top, x, y, round6(s)), crop: zero };
  }
  const refs = Object.keys(set).map((id) => findClip(tl, id)!);
  const le = lockedError(refs);
  if (le) return { error: le };
  return { timeline: withTracks(tl, (tr) => ({ ...tr, clips: tr.clips.map((c) => (set[c.id] ? { ...c, ...set[c.id], keyframes: dropPlaceKeys(c) } : c)) })) };
}

/** A layout sets the position and size, so keyframes on those would fight it. */
function dropPlaceKeys(c: Clip): Clip["keyframes"] {
  const kf = { ...(c.keyframes ?? {}) };
  for (const k of ["x", "y", "scale", "rotation"] as const) delete kf[k];
  return kf;
}

export { clipDuration };

// ---------------------------------------------------------------- brand kit: intro / outro
/** Put a brand intro at the very start (everything moves later) or the outro after the video. */
export function placeBrandClip(tl: Timeline, m: MediaAsset, where: "start" | "end"): OpResult {
  const v = tl.tracks.find((t) => t.kind === "video");
  const a = tl.tracks.find((t) => t.kind === "audio" && !isMusicTrack(t));
  if (!v) return { error: "There's no video track" };
  if (v.locked || (m.has_audio && a?.locked)) return { error: "Unlock V1 and A1 first" };
  const dur = round6(m.duration);
  const at = where === "start" ? 0 : round6(Math.max(0, ...tl.tracks.filter((t) => !isMusicTrack(t)).flatMap((t) => t.clips.map(clipEnd))));
  const base = where === "start" ? rippleInsert(tl, 0, dur) : tl;
  const link = m.has_audio && a ? newId() : null;
  const mk = (): Clip => ({ id: newId(), media_id: m.id, start: at, source_in: 0, source_out: dur, speed: 1, volume: 1,
    transform: { x: 0, y: 0, scale: 1, rotation: 0 }, link_id: link, label: where === "start" ? "Intro" : "Outro" } as Clip);
  const vc = mk(), ac = { ...mk(), id: newId() };
  return {
    timeline: withTracks(base, (t) => t.id === v.id ? { ...t, clips: sortClips([...t.clips, vc]) }
      : link && t.id === a!.id ? { ...t, clips: sortClips([...t.clips, ac]) } : t),
    created: link ? [vc.id, ac.id] : [vc.id],
  };
}

// ---------------------------------------------------------------- teaser (Phase 16 hook checker)
/** Copy what's in [a, b] of the edit (all tracks except music) to the very start as a teaser;
 *  everything (titles, markers…) moves later by its length. Linked picture+sound stay linked. */
export function insertTeaser(tl: Timeline, a: number, b: number): OpResult {
  const len = round6(b - a);
  if (!(len >= 0.5)) return { error: "A teaser needs to be at least half a second long" };
  const parts: { track: string; clip: Clip }[] = [];
  const links = new Map<string, string>();
  for (const t of tl.tracks) {
    if (isMusicTrack(t)) continue;
    for (const c of t.clips) {
      const s = Math.max(a, c.start), e = Math.min(b, clipEnd(c));
      if (e - s < MIN_CLIP) continue;
      const si = c.source_in + (s - c.start) * c.speed;
      const link = c.link_id ? (links.get(c.link_id) ?? (links.set(c.link_id, newId()), links.get(c.link_id)!)) : null;
      parts.push({ track: t.id, clip: { ...c, id: newId(), start: round6(s - a), source_in: round6(si), source_out: round6(si + (e - s) * c.speed),
        link_id: link, transition_in: null } as Clip });
    }
  }
  if (!parts.length) return { error: "There's nothing in that part of the video" };
  const moved = rippleInsert(tl, 0, len);
  return {
    timeline: withTracks(moved, (t) => {
      const add = parts.filter((p) => p.track === t.id).map((p) => p.clip);
      return add.length ? { ...t, clips: sortClips([...t.clips, ...add]) } : t;
    }),
    created: parts.map((p) => p.clip.id),
  };
}
