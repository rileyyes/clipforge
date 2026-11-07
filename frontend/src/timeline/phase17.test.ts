// Phase 17: titles, blurs and markers follow the clip they sit on when you move it by hand.
import { test } from "node:test";
import assert from "node:assert/strict";
import { addBlur, addMarker, addMedia, addTitle, carryWithClips, moveClip, moveClips, splitAt } from "./ops";
import type { MediaAsset, Timeline } from "./types";

const id = (n: number) => n.toString(16).padStart(32, "0");
const asset = (n: number, duration: number): MediaAsset => ({
  id: id(n), original_name: `m${n}.mp4`, stored_name: "x", kind: "video", duration, size_bytes: 1, container: "mp4",
  has_video: true, has_audio: true, variable_frame_rate: false, imported_at: "",
});
const A = asset(1, 10), B = asset(2, 10), CAM = { ...asset(3, 30), has_audio: false };
const ok = (r: any): Timeline => { assert.equal(r.error, undefined, r.error); return r.timeline; };
const empty = (): Timeline => ({ tracks: [
  { id: id(10), kind: "video", name: "V1", muted: false, hidden: false, locked: false, clips: [] },
  { id: id(11), kind: "video", name: "V2", muted: false, hidden: false, locked: false, clips: [] },
  { id: id(12), kind: "audio", name: "A1", muted: false, hidden: false, locked: false, clips: [] },
] });
/** A at 0–10 and B at 10–20 on V1 (+ their sound), a title, marker and blur on each */
function setup(): Timeline {
  let tl = ok(addMedia(empty(), A));
  tl = ok(addMedia(tl, B));
  tl = ok(addTitle(tl, "lower_third", 2));
  tl = ok(addTitle(tl, "lower_third", 13));
  tl = ok(addMarker(tl, 4));
  tl = ok(addMarker(tl, 15));
  tl = ok(addBlur(tl, 3, { x: 0.1, y: 0.1, w: 0.2, h: 0.2 }));
  tl = ok(addBlur(tl, 12, { x: 0.1, y: 0.1, w: 0.2, h: 0.2 }));
  return tl;
}
const v1 = (tl: Timeline) => [...tl.tracks[0].clips].sort((a, b) => a.start - b.start);

test("moving a clip later carries its title, marker and blur", () => {
  const tl = setup();
  const b = v1(tl)[1];
  const out = ok(moveClip(tl, b.id, 25));
  assert.deepEqual(out.titles!.map((t) => t.start), [2, 28]);
  assert.deepEqual(out.markers!.map((m) => m.t), [4, 30]);
  assert.deepEqual(out.blurs!.map((x) => x.start), [3, 27]);
  assert.deepEqual(out.blurs![1].keys.map((k) => k.t), [27]);
});

test("things on clips that didn't move stay put; things over nothing stay put", () => {
  let tl = setup();
  tl = ok(addTitle(tl, "lower_third", 40));      // past the end: over nothing
  const b = v1(tl)[1];
  const out = ok(moveClip(tl, b.id, 30));
  assert.equal(out.titles![0].start, 2);
  assert.equal(out.titles![2].start, 40);
  assert.equal(out.markers![0].t, 4);
});

test("a title at a clip's first frame goes with that clip, not the one ending there", () => {
  let tl = setup();
  tl = ok(addTitle(tl, "lower_third", 10));
  const b = v1(tl)[1];
  const out = ok(moveClip(tl, b.id, 22));
  assert.equal(out.titles![2].start, 22);
});

test("moving several clips together carries everything on them; markers stay sorted", () => {
  const tl = setup();
  const [a, b] = v1(tl);
  const out = ok(moveClips(tl, [a.id, b.id], 5));
  assert.deepEqual(out.titles!.map((t) => t.start), [7, 18]);
  assert.deepEqual(out.markers!.map((m) => m.t), [9, 20]);
  // swap order: move A after B
  const sw = ok(moveClip(tl, a.id, 20));
  assert.deepEqual(sw.markers!.map((m) => m.t), [15, 24]);
  assert.ok(sw.markers!.every((m, i, arr) => i === 0 || arr[i - 1].t <= m.t));
});

test("moving a face cam on V2 leaves titles and markers alone, but its blur goes with it", () => {
  let tl = setup();
  tl = ok(addMedia(tl, CAM, 0, id(11)));
  const cam = tl.tracks[1].clips[0];
  const out = ok(moveClip(tl, cam.id, 5));
  assert.deepEqual(out.titles!.map((t) => t.start), [2, 13]);
  assert.deepEqual(out.markers!.map((m) => m.t), [4, 15]);
  // both blurs were over the cam (the top picture), so both follow it
  assert.deepEqual(out.blurs!.map((x) => x.start), [8, 17]);
});

test("moving to another track at the same time changes nothing; a no-op move returns the same overlays", () => {
  const tl = setup();
  const b = v1(tl)[1];
  const out = ok(moveClip(tl, b.id, 10, id(11)));
  assert.deepEqual(out.titles, tl.titles);
  assert.deepEqual(out.markers, tl.markers);
  assert.equal(carryWithClips(tl, tl), tl);
});

test("after a split, only the moved half carries what's on it", () => {
  let tl = setup();
  const b = v1(tl)[1];
  tl = ok(splitAt(tl, [b.id], 14));
  const right = v1(tl).find((c) => Math.abs(c.start - 14) < 1e-6)!;
  const out = ok(moveClip(tl, right.id, 30));
  assert.equal(out.titles![1].start, 13);     // title at 13 sits on the left half
  assert.equal(out.markers![1].t, 31);        // marker at 15 is on the right half
});

test("a move stopped at 0 shifts things by the real amount", () => {
  let tl = ok(addMedia(empty(), B, 10));
  tl = ok(addTitle(tl, "lower_third", 12));
  const b = v1(tl)[0];
  const out = ok(moveClips(tl, [b.id], -15));   // stops at 0, so it really moved 10 s
  assert.equal(v1(out)[0].start, 0);
  assert.equal(out.titles![0].start, 2);
});
