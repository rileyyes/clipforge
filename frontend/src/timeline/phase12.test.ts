// Phase 12: moving several clips at once, unlink/link picture and sound, markers.
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  addMarker, addMedia, cutRanges, deleteClips, findClip, linkClips, markerNear, moveClip, moveClips,
  removeMarker, splitAt, trimEdge, unlinkClips, updateMarker,
} from "./ops";
import type { MediaAsset, Timeline } from "./types";

const id = (n: number) => n.toString(16).padStart(32, "0");
const media: MediaAsset = {
  id: id(1), original_name: "a.mp4", stored_name: "x.mp4", kind: "video", duration: 10,
  size_bytes: 1, container: "mp4", has_video: true, has_audio: true, variable_frame_rate: false, imported_at: "",
};
const M = { [media.id]: media };
const empty = (): Timeline => ({
  tracks: [
    { id: id(10), kind: "video", name: "V1", muted: false, hidden: false, locked: false, clips: [] },
    { id: id(11), kind: "video", name: "V2", muted: false, hidden: false, locked: false, clips: [] },
    { id: id(12), kind: "audio", name: "A1", muted: false, hidden: false, locked: false, clips: [] },
  ],
});
const ok = (r: any): Timeline => { assert.equal(r.error, undefined, r.error); return r.timeline; };
/** three linked video+audio pairs back to back: 0-10, 10-20, 20-30 */
const three = () => {
  let tl = empty();
  const v: string[] = [], a: string[] = [];
  for (let i = 0; i < 3; i++) { const r = addMedia(tl, media) as any; tl = ok(r); v.push(r.created[0]); a.push(r.created[1]); }
  return { tl, v, a };
};
const start = (tl: Timeline, cid: string) => findClip(tl, cid)!.clip.start;

// ------------------------------------------------------------ multi-clip move
test("moveClips moves every selected clip and its sound by the same amount", () => {
  const { tl, v, a } = three();
  const after = ok(moveClips(tl, [v[1], v[2]], 5));
  assert.deepEqual([start(after, v[0]), start(after, v[1]), start(after, v[2])], [0, 15, 25]);
  assert.deepEqual([start(after, a[1]), start(after, a[2])], [15, 25]);   // linked sound came along
  assert.equal(start(after, a[0]), 0);
});

test("moveClips keeps the group together at 0 and refuses overlaps and locked tracks", () => {
  const { tl, v } = three();
  // move the last two left by 100 s: clamped so the earliest lands at 0... which overlaps clip 1
  assert.match(moveClips(tl, [v[1], v[2]], -100).error!, /overlap/);
  const spaced = ok(moveClips(tl, [v[1], v[2]], 10));                    // 20-30, 30-40
  const back = ok(moveClips(spaced, [v[0]], -5));                          // already at 0: no change
  assert.equal(start(back, v[0]), 0);
  const all = ok(moveClips(spaced, [v[0], v[1], v[2]], -100));            // whole timeline: stops at 0
  assert.deepEqual([start(all, v[0]), start(all, v[1]), start(all, v[2])], [0, 20, 30]);
  const locked: Timeline = { ...tl, tracks: tl.tracks.map((t) => (t.kind === "audio" ? { ...t, locked: true } : t)) };
  assert.match(moveClips(locked, [v[2]], 3).error!, /locked/);
  assert.ok(moveClips(tl, [], 3).error);
});

test("moveClips with one clip matches moveClip", () => {
  const { tl, v } = three();
  const one = ok(moveClips(tl, [v[2]], 4));
  const ref = ok(moveClip(tl, v[2], 24));
  assert.deepEqual(one, ref);
});

// ------------------------------------------------------------ unlink / link
test("unlink lets picture and sound move on their own; link puts them back together", () => {
  const { tl, v, a } = three();
  const un = ok(unlinkClips(tl, [v[2]]));
  assert.equal(findClip(un, v[2])!.clip.link_id, null);
  assert.equal(findClip(un, a[2])!.clip.link_id, null);
  assert.notEqual(findClip(un, v[1])!.clip.link_id, null);                 // others untouched
  assert.match(unlinkClips(un, [v[2]]).error!, /aren't linked/);
  const nudged = ok(moveClip(un, a[2], 20.5));                             // sound only, half a second later
  assert.equal(start(nudged, v[2]), 20);
  assert.equal(start(nudged, a[2]), 20.5);
  // out of line: refused with a clear reason
  assert.match(linkClips(nudged, [v[2], a[2]]).error!, /start and end together/);
  const back = ok(moveClip(nudged, a[2], 20));
  const relinked = ok(linkClips(back, [v[2], a[2]]));
  const L = findClip(relinked, v[2])!.clip.link_id;
  assert.ok(L && L === findClip(relinked, a[2])!.clip.link_id);
  const moved = ok(moveClip(relinked, v[2], 25));                          // they move together again
  assert.equal(start(moved, a[2]), 25);
});

test("link rules: two or more clips, one per track, lined up", () => {
  const { tl, v, a } = three();
  const un = ok(unlinkClips(ok(unlinkClips(tl, [v[0]])), [v[1]]));
  assert.match(linkClips(un, [v[0]]).error!, /at least two/);
  assert.match(linkClips(un, [v[0], v[1]]).error!, /one clip per track/);
  assert.match(linkClips(un, [v[0], a[1], a[0]]).error!, /one clip per track/);
  assert.match(linkClips(tl, [v[0], a[0]]).error!, /already linked/);
  assert.match(linkClips(un, [v[0], a[1]]).error!, /start and end together/);
  // same place on the timeline but a different moment of the recording (sound slipped)
  const slipped = { ...un, tracks: un.tracks.map((t) => ({ ...t, clips: t.clips.map((c) => (c.id === a[0] ? { ...c, source_in: 1, source_out: 11 } : c)) })) };
  assert.match(linkClips(slipped, [v[0], a[0]]).error!, /different moments/);
  const trimmed = ok(trimEdge(un, a[0], "end", 8, M));                     // same start, shorter sound
  assert.match(linkClips(trimmed, [v[0], a[0]]).error!, /start and end together/);
});

test("split keeps re-linked clips linked in pairs", () => {
  const { tl, v, a } = three();
  let t = ok(linkClips(ok(unlinkClips(tl, [v[2]])), [v[2], a[2]]));
  t = ok(splitAt(t, [v[2]], 24));
  const vids = t.tracks[0].clips.filter((c) => c.start >= 20);
  const auds = t.tracks[2].clips.filter((c) => c.start >= 20);
  assert.equal(vids.length, 2);
  assert.equal(auds.length, 2);
  assert.equal(new Set(vids.map((c) => c.link_id)).size, 2);
  for (const c of vids) assert.ok(auds.some((x) => x.link_id === c.link_id && x.start === c.start));
});

// ------------------------------------------------------------ markers
test("markers: add, rename, colour, move, remove, find next and previous", () => {
  let tl = three().tl;
  const r1 = addMarker(tl, 12) as any;
  tl = ok(r1);
  assert.match(addMarker(tl, 12.02).error!, /already/);
  const r2 = addMarker(tl, 4) as any;
  tl = ok(r2);
  assert.deepEqual(tl.markers!.map((m) => m.t), [4, 12]);                 // kept in time order
  tl = ok(updateMarker(tl, r1.id, { label: "Boss fight", color: "#4cc9f0" }));
  assert.equal(tl.markers![1].label, "Boss fight");
  assert.match(updateMarker(tl, r1.id, { color: "blue" }).error!, /Colours/);
  tl = ok(updateMarker(tl, r1.id, { t: 2 }));
  assert.deepEqual(tl.markers!.map((m) => m.label), ["Boss fight", ""]);
  assert.equal(ok(updateMarker(tl, r1.id, { label: "x".repeat(150) })).markers![0].label.length, 100);
  assert.equal(markerNear(tl, 0, 1)!.t, 2);
  assert.equal(markerNear(tl, 2, 1)!.t, 4);
  assert.equal(markerNear(tl, 4, 1), null);
  assert.equal(markerNear(tl, 4, -1)!.t, 2);
  assert.equal(markerNear(tl, 2, -1), null);
  tl = ok(removeMarker(tl, r2.id));
  assert.equal(tl.markers!.length, 1);
  assert.ok(removeMarker(tl, r2.id).error);
  assert.equal(ok(addMarker(tl, -3)).markers![0].t, 0);
});

test("markers move with ripple delete and transcript cuts", () => {
  const { tl: base, v } = three();
  let tl = base;
  for (const t of [5, 15, 25]) tl = ok(addMarker(tl, t));
  const rip = ok(deleteClips(tl, [v[1]], true));                          // 10-20 removed
  assert.deepEqual(rip.markers!.map((m) => m.t), [5, 10, 15]);             // one inside goes to the cut
  const plain = ok(deleteClips(tl, [v[1]], false));                        // no ripple: nothing moves
  assert.deepEqual(plain.markers!.map((m) => m.t), [5, 15, 25]);
  const cut = ok(cutRanges(tl, [[2, 4], [14, 16]]));
  assert.deepEqual(cut.markers!.map((m) => m.t), [3, 12, 21]);
});
