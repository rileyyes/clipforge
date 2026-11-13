// Phase 19: ticker (timers, money), route drawing, slow push, sound design, pacing checker.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { addMarker, addMedia, addTitle, setTransition, splitAt, updateTitle } from "./ops";
import { newEffectAt } from "./effects";
import { paceScore, punchIns, pyRound, realTimeDuration, routePart, routeProgress, slowPush, slowStretches, soundDesign,
  SOUND_DESIGN, tickerAt, tickerHot } from "./phase19";
import type { Effect, MediaAsset, Timeline, Title } from "./types";

const id = (n: number) => n.toString(16).padStart(32, "0");
const asset = (n: number, duration: number): MediaAsset => ({
  id: id(n), original_name: `m${n}.mp4`, stored_name: "x", kind: "video", duration, size_bytes: 1, container: "mp4",
  has_video: true, has_audio: true, variable_frame_rate: false, imported_at: "",
});
const A = asset(1, 60), B = { ...asset(2, 60), has_audio: false };
const ok = (r: any): Timeline => { assert.equal(r.error, undefined, r.error); return r.timeline; };
const empty = (): Timeline => ({ tracks: [
  { id: id(10), kind: "video", name: "V1", muted: false, hidden: false, locked: false, clips: [] },
  { id: id(11), kind: "video", name: "V2", muted: false, hidden: false, locked: false, clips: [] },
  { id: id(12), kind: "audio", name: "A1", muted: false, hidden: false, locked: false, clips: [] },
] });

test("ticker: same text as the export at every sampled moment (ticker_vectors.json)", () => {
  const cases = JSON.parse(readFileSync(new URL("../../../backend/tests/data/ticker_vectors.json", import.meta.url), "utf8"));
  assert.ok(cases.length >= 6);
  for (const c of cases) {
    const t = { id: "x", start: 0, template: "ticker", text: "", subtext: "", color: "#fff", accent: "#f00", align: "left", size: 1, ...c.title } as Title;
    for (const [tt, want] of c.samples) assert.equal(tickerAt(tt, t), want, `${JSON.stringify(c.title)} at ${tt}`);
  }
  assert.deepEqual([pyRound(2.5), pyRound(3.5), pyRound(-2.5), pyRound(2.4)], [2, 4, -2, 2]);
});

test("ticker: real-time length, last ten seconds of a countdown are hot", () => {
  const t = { id: "x", start: 0, duration: 4, template: "ticker", count_from: 30, count_to: 0, format: "time" } as Title;
  assert.equal(realTimeDuration(t), 30.3);
  assert.equal(tickerHot("0:10", t), true); assert.equal(tickerHot("0:11", t), false);
  assert.equal(tickerHot("0:05", { ...t, count_from: 0, count_to: 30 }), false);      // counting up
  assert.equal(tickerHot("$5", { ...t, format: "money" }), false);
});

test("route: drawn by length in 30 steps, tip on the line", () => {
  const pts: [number, number][] = [[0, 0], [100, 0], [100, 100]];
  assert.deepEqual(routePart(pts, 0.25), [[0, 0], [50, 0]]);
  assert.deepEqual(routePart(pts, 0.75), [[0, 0], [100, 0], [100, 50]]);
  assert.deepEqual(routePart(pts, 1), pts);
  assert.equal(routeProgress(0, 5), 1 / 30);
  assert.equal(routeProgress(2.5, 5), 1);                                 // drawn after half the title (≤ 2 s)
  assert.equal(routeProgress(1.25, 5), Math.ceil(1.25 / 2 * 30) / 30);
  // points are kept inside the frame, 20 at most
  let tl = ok(addTitle(empty(), "route", 0));
  const tid = tl.titles![0].id;
  tl = ok(updateTitle(tl, tid, { points: Array.from({ length: 30 }, (_, i) => [i / 10 - 1, 2] as [number, number]) }));
  assert.equal(tl.titles![0].points!.length, 20);
  assert.ok(tl.titles![0].points!.every(([x, y]) => x >= 0 && x <= 1 && y === 1));
});

test("slow push: steady zoom across the whole clip, and off again", () => {
  let tl = ok(addMedia(empty(), A));
  const v = tl.tracks[0].clips[0];
  const pin = ok(slowPush(tl, v.id, "in")).tracks[0].clips[0];
  assert.deepEqual(pin.keyframes!.scale!.map((k) => [k.t, k.v]), [[0, 1], [60, 1.12]]);
  const pout = ok(slowPush(tl, v.id, "out")).tracks[0].clips[0];
  assert.deepEqual(pout.keyframes!.scale!.map((k) => k.v), [1.12, 1]);
  tl = ok(slowPush(tl, v.id, "in"));
  assert.equal(ok(slowPush(tl, v.id, "off")).tracks[0].clips[0].keyframes?.scale?.length ?? 0, 0);
  assert.ok("error" in slowPush(tl, tl.tracks[2].clips[0].id, "in"));   // not on sound
});

test("sound design: whoosh into transitions and zooms, riser + hit into markers; replaces its own", () => {
  let tl = ok(addMedia(empty(), A));
  tl = ok(splitAt(tl, tl.tracks.flatMap((t) => t.clips.map((c) => c.id)), 20));
  const second = tl.tracks[0].clips.find((c) => c.start > 1)!;
  tl = ok(setTransition(tl, second.id, { kind: "crossfade", duration: 0.5 }));
  tl = ok(addMarker(tl, 30));
  tl = ok(addTitle(tl, "big_title", 40));
  const zoom = newEffectAt(tl, 10, "zoom")!;
  const mine = newEffectAt(tl, 12, "sfx", { sound: "airhorn" })!;
  const r = soundDesign(tl, [zoom, mine]);
  const sd = r.effects.filter((e) => e.context === SOUND_DESIGN);
  const at = (e: Effect) => +e.source_time.toFixed(2);
  assert.deepEqual(sd.map((e) => [e.sound, at(e)]).sort(), [["impact", 30], ["impact", 40], ["riser", 28.4], ["whoosh", 19.65], ["whoosh", 9.88]].sort());
  assert.ok(r.effects.includes(mine) && r.effects.includes(zoom));
  const again = soundDesign(tl, r.effects);
  assert.equal(again.effects.length, r.effects.length);                  // re-running doesn't pile up
});

test("pacing: still stretches found; cuts, B-roll, titles, zooms and moving clips count as change", () => {
  let tl = ok(addMedia(empty(), A));
  const one = slowStretches(tl, [], "lively");
  assert.deepEqual(one, [{ start: 0, end: 60 }]);
  assert.equal(paceScore(tl, one), 0);
  // a split that carries on isn't a change; a real cut (different footage) is
  tl = ok(splitAt(tl, tl.tracks.flatMap((t) => t.clips.map((c) => c.id)), 30));
  assert.deepEqual(slowStretches(tl, [], "lively"), [{ start: 0, end: 60 }]);
  tl = ok(addMedia(tl, B, 10, id(11)));                                 // B-roll 10-70 on V2 -> changes at 10 (and its end)
  tl = { ...tl, tracks: tl.tracks.map((t) => t.id === id(11) ? { ...t, clips: t.clips.map((c) => ({ ...c, source_out: 3 })) } : t) };  // 10-13
  tl = ok(addTitle(tl, "pop_text", 40));
  const zoom = newEffectAt(tl, 50, "zoom")!;
  const s = slowStretches(tl, [zoom], "lively").map((x) => [x.start, x.end]);
  assert.deepEqual(s, [[0, 10], [13, 40], [40, 50], [50, 60]]);
  assert.deepEqual(slowStretches(tl, [zoom], "relaxed").map((x) => [x.start, x.end]), [[0, 10], [13, 40], [40, 50], [50, 60]]);
  assert.deepEqual(slowStretches(tl, [zoom], "relaxed", null).length, 4);
  // footage that moves isn't flagged
  const busy = { step: 0.1, values: Array.from({ length: 600 }, (_, i) => (i >= 150 && i < 400 ? 0.8 : 0)) };
  assert.deepEqual(slowStretches(tl, [zoom], "lively", busy).map((x) => [x.start, x.end]), [[0, 10], [40, 50], [50, 60]]);
  // an animated clip (slow push) isn't flagged
  const v1 = tl.tracks[0].clips.find((c) => c.start === 0)!;
  const pushed = ok(slowPush(tl, v1.id, "in"));
  assert.deepEqual(slowStretches(pushed, [zoom], "lively").map((x) => [x.start, x.end]), [[30, 40], [40, 50], [50, 60]]);   // only 0-30 is pushed
  // punch-ins break a stretch up so no gap is longer than the pace
  const fix = punchIns(tl, { start: 13, end: 40 }, "lively");
  assert.equal(fix.length, 6);
  assert.ok(slowStretches(tl, [zoom, ...fix], "lively").every((x) => !(x.start >= 13 && x.end <= 40)));
});

test("new templates have useful defaults (timer, money counter, stamp, route, highlighter)", () => {
  const t1 = ok(addTitle(empty(), "ticker", 0, "Timer")).titles![0];
  assert.deepEqual([t1.format, t1.count_from, t1.count_to, t1.duration], ["time", 10, 0, 10.3]);
  const t2 = ok(addTitle(empty(), "ticker", 0, "Money counter")).titles![0];
  assert.deepEqual([t2.format, t2.count_to], ["money", 10000]);
  assert.equal(tickerAt(t2.duration, t2), "$10,000");
  for (const [tpl, label] of [["stamp", "Time & place"], ["route", "Route on a map"], ["highlight", "Highlighter"]] as const) {
    const t = ok(addTitle(empty(), tpl, 0, label)).titles![0];
    assert.equal(t.template, tpl);
  }
});
