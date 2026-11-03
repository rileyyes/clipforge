import { test } from "node:test";
import assert from "node:assert/strict";
import { colorCss, cropCss, keyframeTimes, propAt, removeKeyframe, setKeyframe, valueAt } from "./keyframes";
import { addMedia, splitAt, updateClip, findClip } from "./ops";
import type { Clip, Keyframe, MediaAsset, Timeline } from "./types";

const K = (...p: [number, number, Keyframe["ease"]][]): Keyframe[] => p.map(([t, v, ease]) => ({ t, v, ease }));
const near = (a: number, b: number, tol = 1e-9) => assert.ok(Math.abs(a - b) < tol, `${a} != ${b}`);

test("valueAt matches the backend vectors (linear, ease, hold, clamps)", () => {
  const k = K([1, 0, "linear"], [3, 10, "ease"], [5, 20, "hold"], [7, 0, "linear"]);
  near(valueAt(k, 0, 99), 0); near(valueAt(k, 9, 99), 0);
  near(valueAt(k, 2, 99), 5);
  near(valueAt(k, 3.5, 99), 10 + 10 * 0.15625);
  near(valueAt(k, 4, 99), 15);
  near(valueAt(k, 6.9, 99), 20);
  near(valueAt([], 3, 7), 7);
});

test("setKeyframe sorts, replaces nearby, clamps; removeKeyframe", () => {
  let k = setKeyframe(undefined, "opacity", 2, 0.5);
  k = setKeyframe(k, "opacity", 1, 2);   // clamped to 1
  k = setKeyframe(k, "opacity", 2.004, 0.25, "ease"); // replaces t=2
  assert.deepEqual(k.map((x) => [x.t, x.v, x.ease]), [[1, 1, undefined], [2, 0.25, "ease"]]);
  assert.deepEqual(removeKeyframe(k, 1).map((x) => x.t), [2]);
});

const media: MediaAsset = { id: "1".padStart(32, "0"), original_name: "a.mp4", stored_name: "x.mp4", kind: "video", duration: 10,
  size_bytes: 1, container: "mp4", has_video: true, has_audio: true, variable_frame_rate: false, imported_at: "" };
const tl0 = (): Timeline => ({ tracks: [
  { id: "a".padStart(32, "0"), kind: "video", name: "V1", muted: false, hidden: false, locked: false, clips: [] },
  { id: "b".padStart(32, "0"), kind: "audio", name: "A1", muted: false, hidden: false, locked: false, clips: [] }] });

test("keyframes are on source time: they survive split and follow speed", () => {
  const r = addMedia(tl0(), media) as any;
  const vid = r.created[0], aid = r.created[1];
  let tl: Timeline = updateClip(r.timeline, vid, { keyframes: { x: K([0, -100, "linear"], [10, 100, "linear"]) } }).timeline!;
  const c = findClip(tl, vid)!.clip;
  near(propAt(c, "x", 5), 0);
  tl = splitAt(tl, [vid], 5).timeline!;
  const right = tl.tracks[0].clips.find((x) => x.start >= 5)!;
  near(propAt(right, "x", 7.5), 50); // same picture, same position
  const fast = updateClip(tl, right.id, { speed: 2 }).timeline!.tracks[0].clips.find((x) => x.id === right.id)!;
  near(propAt(fast, "x", 6), 40); // source 5 + 1 s * 2 = 7 s -> 70% of the way
  assert.deepEqual(keyframeTimes(c), [0, 10]);
  // video props can't go on audio clips and vice versa
  assert.ok(updateClip(tl, aid, { keyframes: { x: K([0, 1, "linear"]) } }).error);
  assert.ok(updateClip(tl, vid, { keyframes: { volume: K([0, 1, "linear"]) } }).error);
  assert.ok(updateClip(tl, vid, { transform: { opacity: 2 } }).error);
  assert.ok(updateClip(tl, vid, { crop: { left: 0.5, right: 0.5, top: 0, bottom: 0 } }).error);
  // emptying a property's keyframes removes the key entirely
  const cleared = updateClip(tl, vid, { keyframes: { x: [] } }).timeline!;
  assert.equal(findClip(cleared, vid)!.clip.keyframes?.x, undefined);
});

test("preview CSS for colour and crop", () => {
  assert.equal(colorCss({ brightness: 0, contrast: 1, saturation: 1, gamma: 1, temperature: 0, look: "none" }), "");
  assert.match(colorCss({ brightness: 0, contrast: 1, saturation: 0, gamma: 1, temperature: 0, look: "bw" }), /saturate\(0\.000\).*grayscale\(1\)/);
  assert.equal(cropCss({ left: 0.1, right: 0, top: 0.25, bottom: 0 }), "inset(25.000% 0.000% 0.000% 10.000%)");
  assert.equal(cropCss({ left: 0, right: 0, top: 0, bottom: 0 }), undefined);
});
