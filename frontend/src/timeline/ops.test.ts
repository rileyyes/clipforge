import { test } from "node:test";
import assert from "node:assert/strict";
import {
  addMedia, addTrack, clipDuration, clipEnd, deleteClips, duplicateClip, findClip, moveClip,
  removeTrack, snap, splitAt, timelineDuration, toggleTrack, topVideoClipAt, trimEdge, updateClip, cutRanges, setTrackRole,
} from "./ops";
import { History } from "./history";
import type { MediaAsset, Timeline } from "./types";

const id = (n: number) => n.toString(16).padStart(32, "0");
const media: MediaAsset = {
  id: id(1), original_name: "a.mp4", stored_name: "x.mp4", kind: "video", duration: 10,
  size_bytes: 1, container: "mp4", has_video: true, has_audio: true, variable_frame_rate: false,
  imported_at: "",
};
const music: MediaAsset = { ...media, id: id(2), kind: "audio", has_video: false, duration: 30 };
const M = { [media.id]: media, [music.id]: music };
const empty = (): Timeline => ({
  tracks: [
    { id: id(10), kind: "video", name: "V1", muted: false, hidden: false, locked: false, clips: [] },
    { id: id(11), kind: "video", name: "V2", muted: false, hidden: false, locked: false, clips: [] },
    { id: id(12), kind: "audio", name: "A1", muted: false, hidden: false, locked: false, clips: [] },
  ],
});
const ok = (r: any): Timeline => { assert.equal(r.error, undefined, r.error); return r.timeline; };
const withOne = () => { const r = addMedia(empty(), media) as any; return { tl: ok(r), v: r.created[0], a: r.created[1] }; };

test("addMedia creates linked video+audio clips appended at track end", () => {
  let { tl, v, a } = withOne();
  assert.equal(findClip(tl, v)!.clip.link_id, findClip(tl, a)!.clip.link_id);
  tl = ok(addMedia(tl, media));
  assert.equal(tl.tracks[0].clips[1].start, 10);
  assert.equal(timelineDuration(tl), 20);
});

test("addMedia rejects overlapping placement", () => {
  const { tl } = withOne();
  assert.ok(addMedia(tl, media, 5).error);
});

test("audio-only media goes only to an audio track", () => {
  const tl = ok(addMedia(empty(), music));
  assert.equal(tl.tracks[0].clips.length, 0);
  assert.equal(tl.tracks[2].clips.length, 1);
});

test("split cuts linked clips at the same source point", () => {
  const { tl, v } = withOne();
  const r = splitAt(tl, [v], 4) as any;
  const t = ok(r);
  assert.equal(t.tracks[0].clips.length, 2);
  assert.equal(t.tracks[2].clips.length, 2);
  const [l, rr] = t.tracks[0].clips;
  assert.equal(l.source_out, 4); assert.equal(rr.source_in, 4); assert.equal(rr.start, 4);
  assert.equal(rr.link_id, t.tracks[2].clips[1].link_id);
  assert.notEqual(rr.link_id, l.link_id);
});

test("split respects speed when mapping timeline to source time", () => {
  let { tl, v } = withOne();
  tl = ok(updateClip(tl, v, { speed: 2 })); // 10s source -> 5s on timeline
  tl = ok(splitAt(tl, [v], 2));
  assert.equal(tl.tracks[0].clips[0].source_out, 4);
});

test("split outside clip is an error", () => {
  const { tl, v } = withOne();
  assert.ok(splitAt(tl, [v], 15).error);
});

test("trim end is clamped to media duration and next clip", () => {
  let { tl, v } = withOne();
  tl = ok(trimEdge(tl, v, "end", 6, M));
  assert.equal(clipEnd(findClip(tl, v)!.clip), 6);
  tl = ok(trimEdge(tl, v, "end", 50, M)); // can't extend beyond source
  assert.equal(findClip(tl, v)!.clip.source_out, 10);
});

test("trim start moves in-point and start together; linked audio follows", () => {
  let { tl, v, a } = withOne();
  tl = ok(trimEdge(tl, v, "start", 2.5, M));
  const c = findClip(tl, v)!.clip, ac = findClip(tl, a)!.clip;
  assert.equal(c.start, 2.5); assert.equal(c.source_in, 2.5);
  assert.equal(ac.start, 2.5); assert.equal(ac.source_in, 2.5);
  tl = ok(trimEdge(tl, v, "start", -5, M)); // clamp to source start
  assert.equal(findClip(tl, v)!.clip.source_in, 0);
});

test("trim never makes a clip shorter than the minimum", () => {
  let { tl, v } = withOne();
  tl = ok(trimEdge(tl, v, "end", 0, M));
  assert.ok(clipDuration(findClip(tl, v)!.clip) >= 0.04 - 1e-9);
});

test("move rejects overlap and clamps at zero", () => {
  let { tl, v } = withOne();
  tl = ok(addMedia(tl, media));
  assert.ok(moveClip(tl, v, 5).error);
  tl = ok(moveClip(tl, tl.tracks[0].clips[1].id, 25));
  tl = ok(moveClip(tl, v, -3));
  assert.equal(findClip(tl, v)!.clip.start, 0);
});

test("move to another video track keeps the audio link on A1", () => {
  let { tl, v, a } = withOne();
  tl = ok(moveClip(tl, v, 3, id(11)));
  assert.equal(findClip(tl, v)!.track.name, "V2");
  assert.equal(findClip(tl, a)!.clip.start, 3);
  assert.ok(moveClip(tl, v, 3, id(12)).error, "video clip cannot go to audio track");
});

test("ripple delete closes the gap on affected tracks", () => {
  let { tl, v } = withOne();
  tl = ok(addMedia(tl, media));
  const second = tl.tracks[0].clips[1].id;
  tl = ok(deleteClips(tl, [v], true));
  assert.equal(findClip(tl, second)!.clip.start, 0);
  assert.equal(tl.tracks[2].clips[0].start, 0);
});

test("plain delete leaves a gap", () => {
  let { tl, v } = withOne();
  tl = ok(addMedia(tl, media));
  const second = tl.tracks[0].clips[1].id;
  tl = ok(deleteClips(tl, [v]));
  assert.equal(findClip(tl, second)!.clip.start, 10);
});

test("duplicate places a linked copy after the original", () => {
  let { tl, v } = withOne();
  const r = duplicateClip(tl, v) as any;
  tl = ok(r);
  assert.equal(tl.tracks[0].clips.length, 2);
  assert.equal(tl.tracks[0].clips[1].start, 10);
  assert.equal(tl.tracks[2].clips[1].start, 10);
});

test("locked tracks reject edits", () => {
  let { tl, v } = withOne();
  tl = ok(toggleTrack(tl, id(10), "locked"));
  assert.ok(deleteClips(tl, [v]).error);
  assert.ok(moveClip(tl, v, 4).error);
  assert.ok(splitAt(tl, [v], 3).error);
});

test("speed change that would overlap is rejected", () => {
  let { tl, v } = withOne();
  tl = ok(addMedia(tl, media));
  assert.ok(updateClip(tl, v, { speed: 0.5 }).error);
  assert.ok(updateClip(tl, v, { speed: 10 }).error);
});

test("tracks: add keeps video above audio, remove only when empty", () => {
  let tl = ok(addTrack(empty(), "video"));
  assert.deepEqual(tl.tracks.map((t) => t.name), ["V1", "V2", "V3", "A1"]);
  const { tl: t2 } = withOne();
  assert.ok(removeTrack(t2, id(10)).error);
  const t3 = ok(removeTrack(t2, id(11)));
  assert.equal(t3.tracks.length, 2);
  assert.ok(removeTrack(ok(deleteClips(t3, [t3.tracks[0].clips[0].id])), id(10)).error, "last video track stays");
});

test("snap picks nearest point within threshold", () => {
  assert.equal(snap(4.93, [0, 5, 10], 0.1), 5);
  assert.equal(snap(4.5, [0, 5, 10], 0.1), 4.5);
});

test("topVideoClipAt prefers higher tracks and ignores hidden", () => {
  let { tl } = withOne();
  tl = ok(addMedia(tl, { ...media, has_audio: false, id: id(3) }, 2, id(11)));
  assert.equal(topVideoClipAt(tl, 3)!.track.name, "V2");
  tl = ok(toggleTrack(tl, id(11), "hidden"));
  assert.equal(topVideoClipAt(tl, 3)!.track.name, "V1");
});

test("history undo/redo", () => {
  const h = new History<number>();
  h.push(1, "a"); h.push(2, "b");
  assert.equal(h.undo(3)!.state, 2);
  assert.equal(h.undo(2)!.state, 1);
  assert.equal(h.redo(1)!.state, 2);
  h.push(9, "c");
  assert.equal(h.canRedo, false);
});


test("cutRanges removes stretches from picture + sound together and closes the gaps", () => {
  let { tl } = withOne();                                  // 0-10 s, linked V1 + A1
  tl = ok(addTrack(tl, "audio"));
  const mt = tl.tracks[3].id;
  tl = ok(setTrackRole(tl, mt, "music"));
  tl = { ...tl, tracks: tl.tracks.map((t) => t.id === mt ? { ...t, clips: [{ id: id(99), media_id: music.id, start: 0, source_in: 0, source_out: 30, speed: 1, volume: 1 }] } : t) };
  tl = ok(cutRanges(tl, [[2, 3], [6, 6.5], [2.5, 3.2]]));   // overlapping ranges merge: 2-3.2 and 6-6.5
  const v = tl.tracks[0].clips, a = tl.tracks[2].clips;
  assert.deepEqual(v.map((c) => [c.start, c.source_in, c.source_out]), [[0, 0, 2], [2, 3.2, 6], [4.8, 6.5, 10]]);
  assert.deepEqual(a.map((c) => [c.start, c.source_in, c.source_out]), v.map((c) => [c.start, c.source_in, c.source_out]));
  // each piece of picture stays linked to its own piece of sound, and only to it
  for (let i = 0; i < 3; i++) assert.equal(v[i].link_id, a[i].link_id);
  assert.equal(new Set(v.map((c) => c.link_id)).size, 3);
  // the music isn't cut, just trimmed to the new end with a fade-out
  const m = tl.tracks[3].clips[0];
  assert.equal(m.start, 0); assert.ok(Math.abs(clipEnd(m) - 8.3) < 1e-6); assert.equal(m.fade_out, 2);
  assert.ok(cutRanges(tl, [[1, 1.001]]).error);           // nothing meaningful to cut
  const locked = ok(toggleTrack(tl, tl.tracks[2].id, "locked"));
  assert.ok(cutRanges(locked, [[1, 2]]).error);
});

import { beatTimes, snapCutsToBeats, fitMusicToVideo } from "./ops";

test("cuts snap to the nearest beat with roll edits; linked sound follows; music fits the video", () => {
  let { tl } = withOne();                                   // linked V1+A1 0-10 s (media is 10 s long)
  tl = ok(splitAt(tl, [tl.tracks[0].clips[0].id, tl.tracks[2].clips[0].id], 4));
  tl = ok(cutRanges(tl, [[4, 5]]));                         // a jump cut at 4.0 (sources 0-4 | 5-10)
  tl = ok(addTrack(tl, "audio"));
  const mt = tl.tracks[3].id;
  tl = ok(setTrackRole(tl, mt, "music"));
  tl = { ...tl, tracks: tl.tracks.map((t) => t.id === mt ? { ...t, clips: [{ id: id(98), media_id: music.id, start: 0, source_in: 2, source_out: 30, speed: 1, volume: 1 }] } : t) };
  const beats = beatTimes(tl, { [music.id]: [2.5, 3.0, 6.1, 6.6] });
  assert.deepEqual(beats, [0.5, 1, 4.1, 4.6]);
  const r = snapCutsToBeats(tl, beats, M);
  const out = ok(r);
  assert.equal(r.count, 1);
  const v = out.tracks[0].clips, a = out.tracks[2].clips;
  assert.ok(Math.abs(clipEnd(v[0]) - 4.1) < 1e-6 && Math.abs(v[1].start - 4.1) < 1e-6);
  assert.ok(Math.abs(v[0].source_out - 4.1) < 1e-6 && Math.abs(v[1].source_in - 5.1) < 1e-6);
  assert.deepEqual(a.map((c) => [c.start, c.source_in, c.source_out]), v.map((c) => [c.start, c.source_in, c.source_out]));
  assert.ok(Math.abs(clipEnd(v[1]) - 9) < 1e-6);            // nothing else moved
  assert.ok(snapCutsToBeats(out, beats, M).error);          // already on the beat
  const fit = ok(fitMusicToVideo(out));
  const m = fit.tracks[3].clips[0];
  assert.ok(Math.abs(clipEnd(m) - 9) < 1e-6 && m.fade_out === 2);
});

test("snapping skips cuts with no spare footage", () => {
  let { tl } = withOne();
  tl = ok(splitAt(tl, [tl.tracks[0].clips[0].id, tl.tracks[2].clips[0].id], 9.9));
  const r = snapCutsToBeats(tl, [9.95], M, 0.25);       // the second piece would be < 0.09 s
  assert.ok(r.error && /spare footage/.test(r.error));
});

import { addTitle, addBlur } from "./ops";

test("ripple delete moves titles and blurs along with the picture", () => {
  let { tl } = withOne();
  tl = ok(addMedia(tl, media));                                   // two linked pairs: 0-10, 10-20
  let r = addTitle(tl, "lower_third", 12); tl = ok(r);
  r = addBlur(tl, 15, { x: 0.1, y: 0.1, w: 0.2, h: 0.2 }); tl = ok(r);
  r = addTitle(tl, "big_title", 3); tl = ok(r);                    // inside the deleted clip
  const first = tl.tracks[0].clips[0].id;
  const out = ok(deleteClips(tl, [first], true));
  const ts = [...out.titles!].sort((a, b) => a.start - b.start);
  assert.deepEqual(ts.map((t) => t.start), [0, 2]);               // 3 -> start of the gap (0), 12 -> 2
  assert.equal(out.blurs![0].start, 5);
  assert.equal(out.blurs![0].keys[0].t, 5);
  const plain = ok(deleteClips(tl, [first], false));               // no ripple: nothing moves
  assert.deepEqual([...plain.titles!].map((t) => t.start).sort((a, b) => a - b), [3, 12]);
});

import { transitionAt, setTransition } from "./ops";

test("transitionAt: centred on the cut, both pictures at the right moments", () => {
  let { tl } = withOne();
  tl = ok(addMedia(tl, media));                                // 0-10, 10-20 (V1)
  const b = tl.tracks[0].clips[1];
  tl = ok(setTransition(tl, b.id, { kind: "wipe_left", duration: 1 }));
  const v = tl.tracks[0];
  assert.equal(transitionAt(v, 9.4), null);
  const s = transitionAt(v, 9.75)!;
  assert.equal(s.kind, "wipe_left");
  assert.ok(Math.abs(s.p - 0.25) < 1e-9 && Math.abs(s.aTime - 9.75) < 1e-9 && Math.abs(s.bTime - 0) < 1e-9);
  const m = transitionAt(v, 10.25)!;
  assert.ok(Math.abs(m.p - 0.75) < 1e-9 && Math.abs(m.aTime - 10.25) < 1e-9 && Math.abs(m.bTime - 0.25) < 1e-9);
  assert.equal(transitionAt(v, 10.5), null);
});
