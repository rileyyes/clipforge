// Phase 15: freeze frame, reverse, speed ramps, layouts.
import { test } from "node:test";
import assert from "node:assert/strict";
import { addMarker, addMedia, addMusic, clipDuration, clipEnd, MUSIC_DEFAULTS } from "./ops";
import { applyLayout, insertFreeze, RAMP_SLOWMO, RAMP_SPEEDUP, rippleInsert, speedRamp, useReversed } from "./pro";
import type { Clip, MediaAsset, Timeline } from "./types";

const id = (n: number) => n.toString(16).padStart(32, "0");
const asset = (n: number, duration: number, audio = true, video = true): MediaAsset => ({
  id: id(n), original_name: `m${n}.mp4`, stored_name: "x", kind: video ? "video" : "audio", duration, size_bytes: 1, container: "mp4",
  has_video: video, has_audio: audio, variable_frame_rate: false, imported_at: "",
});
const VID = asset(1, 20), SONG = asset(2, 60, true, false), FREEZE = asset(3, 2, false), REV = asset(4, 20), CAM = asset(5, 20, false);
const ok = (r: any): Timeline => { assert.equal(r.error, undefined, r.error); return r.timeline; };
const empty = (): Timeline => ({ tracks: [
  { id: id(10), kind: "video", name: "V1", muted: false, hidden: false, locked: false, clips: [] },
  { id: id(11), kind: "video", name: "V2", muted: false, hidden: false, locked: false, clips: [] },
  { id: id(12), kind: "audio", name: "A1", muted: false, hidden: false, locked: false, clips: [] },
] });
const base = () => ok(addMedia(empty(), VID));
const v1 = (tl: Timeline) => [...tl.tracks[0].clips].sort((a, b) => a.start - b.start);
const a1 = (tl: Timeline) => [...tl.tracks[2].clips].sort((a, b) => a.start - b.start);
const end = (tl: Timeline, i: number) => Math.max(0, ...tl.tracks[i].clips.map(clipEnd));
/** every clip on a track in order with no overlap; linked clips start/end together */
function sane(tl: Timeline) {
  for (const tr of tl.tracks) {
    const cs = [...tr.clips].sort((a, b) => a.start - b.start);
    cs.forEach((c, i) => { if (i) assert.ok(c.start >= clipEnd(cs[i - 1]) - 1e-4, `${tr.name} overlap at ${c.start}`); });
  }
  const by = new Map<string, Clip[]>();
  for (const tr of tl.tracks) for (const c of tr.clips) if (c.link_id) by.set(c.link_id, [...(by.get(c.link_id) ?? []), c]);
  for (const [, g] of by) for (const c of g) {
    assert.ok(Math.abs(c.start - g[0].start) < 1e-4 && Math.abs(clipDuration(c) - clipDuration(g[0])) < 1e-4 && c.speed === g[0].speed, "linked out of sync");
  }
}

test("rippleInsert moves everything later except music", () => {
  let tl = ok(addMusic(base(), SONG, 0, 20, MUSIC_DEFAULTS));
  tl = ok(addMarker(tl, 8));
  const after = rippleInsert(tl, 5, 2);
  assert.deepEqual(v1(after).map((c) => c.start), [0]);              // starts before 5: stays
  assert.equal(after.markers![0].t, 10);
  const music = after.tracks.find((t) => t.role === "music")!;
  assert.equal(music.clips[0].start, 0);
});

test("freeze frame: split, push the rest later, still clip in the gap, sound pauses", () => {
  let tl = ok(addMarker(base(), 5));
  const vid = v1(tl)[0].id;
  tl = ok(insertFreeze(tl, vid, 4, FREEZE));
  sane(tl);
  assert.deepEqual(v1(tl).map((c) => [c.start, c.media_id === FREEZE.id]), [[0, false], [4, true], [6, false]]);
  assert.deepEqual(a1(tl).map((c) => c.start), [0, 6]);               // a 2 s gap in the sound
  assert.equal(end(tl, 0), 22);
  assert.equal(tl.markers![0].t, 7);
  assert.equal(v1(tl)[1].link_id, null);
  // at the very start of a clip: nothing to split
  const b = base();
  const t2 = ok(insertFreeze(b, v1(b)[0].id, 0, FREEZE));
  assert.deepEqual(v1(t2).map((c) => c.start), [0, 2]);
  assert.match(insertFreeze(b, a1(b)[0].id, 3, FREEZE).error!, /video clip/);
});

test("reverse swaps picture and sound for the reversed copy", () => {
  const b = base();
  const tl = ok(useReversed(b, v1(b)[0].id, REV));
  assert.equal(v1(tl)[0].media_id, REV.id);
  assert.equal(a1(tl)[0].media_id, REV.id);
  assert.deepEqual([v1(tl)[0].source_in, v1(tl)[0].source_out], [0, 20]);
  sane(tl);
  const silent = ok(useReversed(b, v1(b)[0].id, { ...REV, has_audio: false }));
  assert.equal(a1(silent)[0].media_id, VID.id);                        // no reversed sound: keep the original
});

test("slow-motion ramp: eases down, holds, eases back; the edit gets longer; picture and sound stay together", () => {
  const tl0 = base();
  const tl = ok(speedRamp(tl0, v1(tl0)[0].id, 5, RAMP_SLOWMO));
  sane(tl);
  const vs = v1(tl), as = a1(tl);
  assert.equal(vs.length, 2 + 2 * RAMP_SLOWMO.steps + 1);
  assert.deepEqual(vs.map((c) => c.start), as.map((c) => c.start));
  const speeds = vs.map((c) => c.speed);
  assert.equal(Math.min(...speeds), RAMP_SLOWMO.target);
  const mid = speeds.indexOf(RAMP_SLOWMO.target);
  for (let i = 1; i <= mid; i++) assert.ok(speeds[i] <= speeds[i - 1] + 1e-9, "eases down");
  for (let i = mid + 1; i < speeds.length; i++) assert.ok(speeds[i] >= speeds[i - 1] - 1e-9, "eases back up");
  // the recording is played continuously, no frames skipped or repeated
  for (let i = 1; i < vs.length; i++) assert.ok(Math.abs(vs[i].source_in - vs[i - 1].source_out) < 1e-5);
  assert.ok(end(tl, 0) > 20.5 && end(tl, 0) < 25, `${end(tl, 0)}`);
});

test("speed-up ramp shortens the edit; refusals", () => {
  const tl0 = base();
  const tl = ok(speedRamp(tl0, v1(tl0)[0].id, 2, RAMP_SPEEDUP));
  sane(tl);
  assert.ok(end(tl, 0) < 19, `${end(tl, 0)}`);
  assert.match(speedRamp(tl0, v1(tl0)[0].id, 19, RAMP_SLOWMO).error!, /Needs/);
  assert.match(speedRamp(tl0, v1(tl0)[0].id, 25, RAMP_SLOWMO).error!, /playhead/);
  assert.match(speedRamp(tl0, v1(tl0)[0].id, 2, { ...RAMP_SLOWMO, target: 0.1 }).error!, /0.25x/);
});

test("layouts: side by side, top/bottom, picture-in-picture, reset", () => {
  let tl = base();
  assert.match(applyLayout(tl, 5, 1920, 1080, "side_by_side").error!, /second clip/);
  tl = { ...tl, tracks: tl.tracks.map((t, i) => (i === 1 ? { ...t, clips: [{ ...v1(tl)[0], id: id(99), media_id: CAM.id, link_id: null }] } : t)) };
  const sbs = ok(applyLayout(tl, 5, 1920, 1080, "side_by_side"));
  assert.deepEqual([sbs.tracks[0].clips[0].transform.x, sbs.tracks[1].clips[0].transform.x], [-480, 480]);
  assert.deepEqual(sbs.tracks[1].clips[0].crop, { left: 0.25, right: 0.25, top: 0, bottom: 0 });
  const tb = ok(applyLayout(tl, 5, 1920, 1080, "top_bottom"));
  assert.deepEqual([tb.tracks[0].clips[0].transform.y, tb.tracks[1].clips[0].transform.y], [-270, 270]);
  const pip = ok(applyLayout(tl, 5, 1920, 1080, "pip", "tr", 0.3));
  const p = pip.tracks[1].clips[0].transform;
  assert.equal(p.scale, 0.3);
  assert.ok(p.x > 0 && p.y < 0);                                       // top right
  assert.equal(Math.round(p.x + 0.15 * 1920 + 0.03 * 1920), 960);       // its right edge sits 3 % from the frame's edge
  const reset = ok(applyLayout(pip, 5, 1920, 1080, "reset"));
  assert.deepEqual(reset.tracks[1].clips[0].transform, { ...p, x: 0, y: 0, scale: 1, rotation: 0 });
});
