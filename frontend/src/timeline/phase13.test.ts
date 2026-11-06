// Phase 13: type a new time for an effect (pop-up text, zoom, sound, bleep…).
import { test } from "node:test";
import assert from "node:assert/strict";
import { effectTime, moveEffectTo, newEffectAt, parseTime } from "./effects";
import type { Clip, Effect, Timeline } from "./types";

const id = (n: number) => n.toString(16).padStart(32, "0");
const A = id(1), B = id(2), MUSIC = id(3);
const clip = (n: number, media: string, start: number, si: number, so: number, speed = 1): Clip => ({
  id: id(100 + n), media_id: media, start, source_in: si, source_out: so, speed, volume: 1,
  transform: { x: 0, y: 0, scale: 1, rotation: 0 }, link_id: null, label: null,
} as unknown as Clip);
// V1: A 0-10 (source 5-15), B 10-14 at 2x (source 0-8). A1: music 0-20.
const tl: Timeline = {
  tracks: [
    { id: id(10), kind: "video", name: "V1", muted: false, hidden: false, locked: false, clips: [clip(1, A, 0, 5, 15), clip(2, B, 10, 0, 8, 2)] },
    { id: id(12), kind: "audio", name: "A1", muted: false, hidden: false, locked: false, clips: [clip(3, MUSIC, 0, 0, 20)] },
  ],
};
const near = (a: number | null, b: number, eps = 0.01) => assert.ok(a !== null && Math.abs(a - b) < eps, `${a} vs ${b}`);

test("parseTime accepts the ways people type a time", () => {
  assert.equal(parseTime("20.8"), 20.8);
  assert.equal(parseTime(" 20.8s "), 20.8);
  assert.equal(parseTime("0:20.80"), 20.8);
  assert.equal(parseTime("1:02.5"), 62.5);
  assert.equal(parseTime("1:02:03.5"), 3723.5);
  assert.equal(parseTime("45"), 45);
  assert.equal(parseTime(".5"), 0.5);
  for (const bad of ["", "abc", "1:75", "-3", "1::2", "2.3.4", "1:2:3:4", "12a"]) assert.equal(parseTime(bad), null, bad);
});

test("moving pop-up text re-pins it to the footage at the new time", () => {
  const e = newEffectAt(tl, 2, "text")!;
  near(effectTime(tl, e), 2);
  const m = moveEffectTo(tl, e, 7.25) as Effect;
  assert.equal(m.media_id, A);
  near(m.source_time, 12.25);
  near(effectTime(tl, m), 7.25);
  assert.equal(m.text, e.text);                       // everything else is kept
  assert.equal(m.id, e.id);
  // onto the second clip (another recording, at 2x speed)
  const m2 = moveEffectTo(tl, e, 12) as Effect;
  assert.equal(m2.media_id, B);
  near(m2.source_time, 4);
  near(effectTime(tl, m2), 12);
  // exactly on a cut: it goes on the clip that starts there
  const m3 = moveEffectTo(tl, e, 10) as Effect;
  assert.equal(m3.media_id, B);
  near(effectTime(tl, m3), 10);
});

test("sounds and bleeps pin to the audio; nothing there is refused", () => {
  const s = newEffectAt(tl, 1, "sfx")!;
  const m = moveEffectTo(tl, s, 16) as Effect;      // past the video, still music underneath
  assert.equal(m.media_id, MUSIC);
  near(effectTime(tl, m), 16);
  const z = newEffectAt(tl, 1, "zoom")!;
  assert.match((moveEffectTo(tl, z, 30) as any).error, /no footage/);
  assert.match((moveEffectTo(tl, z, -1) as any).error, /Type a time/);
  assert.match((moveEffectTo(tl, z, NaN) as any).error, /Type a time/);
  const moved = moveEffectTo(tl, z, 15) as Effect;   // only music at 15: a video effect falls back to it
  assert.equal(moved.media_id, MUSIC);
});

test("an effect whose moment was cut out can be put back by typing a time", () => {
  const e = newEffectAt(tl, 2, "text")!;
  const cut: Timeline = { ...tl, tracks: [{ ...tl.tracks[0], clips: [tl.tracks[0].clips[1]] }, tl.tracks[1]] };
  assert.equal(effectTime({ ...cut, tracks: [cut.tracks[0]] }, e), null);
  const back = moveEffectTo(cut, e, 11) as Effect;
  near(effectTime(cut, back), 11);
});
