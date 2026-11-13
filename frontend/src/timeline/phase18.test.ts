// Phase 18: counters, counts, callout cards and the tally, combos, keep-only, who's talking, text styles.
import { test } from "node:test";
import assert from "node:assert/strict";
import { addMedia, addTitle, cutRanges, setTrackRole, setTrackTag, splitAt, timelineDuration, updateTitle } from "./ops";
import { addCounter, addCount, applyStyle, COMBOS, countAt, counterTicks, counterValue, countCards, keepOnly, removeCounter,
  styleOf, tallyInfo, TEXT_PRESETS, trackTalk, updateCounter } from "./phase18";
import type { Effect, MediaAsset, Timeline } from "./types";

const id = (n: number) => n.toString(16).padStart(32, "0");
const asset = (n: number, duration: number): MediaAsset => ({
  id: id(n), original_name: `m${n}.mp4`, stored_name: "x", kind: "video", duration, size_bytes: 1, container: "mp4",
  has_video: true, has_audio: true, variable_frame_rate: false, imported_at: "",
});
const A = asset(1, 60);
const ok = (r: any): Timeline => { assert.equal(r.error, undefined, r.error); return r.timeline; };
const empty = (): Timeline => ({ tracks: [
  { id: id(10), kind: "video", name: "V1", muted: false, hidden: false, locked: false, clips: [] },
  { id: id(12), kind: "audio", name: "A1", muted: false, hidden: false, locked: false, clips: [] },
] });
const base = () => ok(addMedia(empty(), A));

test("Count it makes the counter (if needed), a +1 and a numbered callout card, together", () => {
  let tl = base();
  let fx: Effect[] = [];
  const r1 = addCount(tl, fx, 5, "Steve", "Machete");
  assert.ok(!("error" in r1));
  if ("error" in r1) return;
  tl = r1.timeline; fx = r1.effects;
  assert.equal(tl.counters!.length, 1);
  assert.equal(fx.length, 1);
  assert.equal(fx[0].kind, "count"); assert.equal(fx[0].counter, tl.counters![0].id); assert.equal(fx[0].sound, "boom");
  const card = tl.titles!.find((t) => t.id === r1.titleId)!;
  assert.equal(card.template, "count_card"); assert.equal(card.text, "Steve"); assert.equal(card.subtext, "Machete");
  const r2 = addCount(tl, fx, 2, "", "");
  assert.ok(!("error" in r2));
  if ("error" in r2) return;
  assert.equal(r2.timeline.counters!.length, 1);                      // the same counter
  assert.deepEqual(countCards(r2.timeline).map((c) => [c.n, c.text]), [[1, "Name"], [2, "Steve"]]);   // numbered by time
  const ticks = counterTicks(r2.timeline, r2.effects, r2.timeline.counters![0].id);
  assert.deepEqual(ticks.map((x) => +x.toFixed(3)), [2, 5]);
  const c = r2.timeline.counters![0];
  assert.deepEqual([1, 2, 4, 5, 9].map((t) => counterValue(c, ticks, t)), [0, 1, 1, 2, 2]);
  assert.ok("error" in addCount(empty(), [], 3, "x", "y"));            // nothing to count on
});

test("counts follow the footage: a cut-out count stops counting, moving pieces moves the tick", () => {
  const r = addCount(base(), [], 10, "A", "");
  if ("error" in r) throw new Error(r.error);
  const cid = r.timeline.counters![0].id;
  const cut = ok(cutRanges(r.timeline, [[8, 12]]));
  assert.deepEqual(counterTicks(cut, r.effects, cid), []);
  const cut2 = ok(cutRanges(r.timeline, [[2, 4]]));                    // earlier cut: the tick moves 2 s earlier
  assert.deepEqual(counterTicks(cut2, r.effects, cid).map((x) => +x.toFixed(3)), [8]);
  // a disabled count doesn't count
  assert.deepEqual(counterTicks(r.timeline, r.effects.map((e) => ({ ...e, enabled: false })), cid), []);
});

test("counters: limits, validation, removing takes its counts with it", () => {
  let tl = base();
  for (let i = 0; i < 4; i++) tl = ok(addCounter(tl));
  assert.ok("error" in addCounter(tl));
  const [c1, c2] = tl.counters!;
  assert.ok(c2.y > c1.y);                                                // stacked, not on top of each other
  assert.ok("error" in updateCounter(tl, c1.id, { color: "red" }));
  assert.ok("error" in updateCounter(tl, c1.id, { start: 10, end: 5 }));
  const u = ok(updateCounter(tl, c1.id, { start_value: 12.4, size: 9, label: "x".repeat(40) })).counters![0];
  assert.deepEqual([u.start_value, u.size, u.label.length], [12, 2, 24]);
  const e1 = countAt(tl, c1.id, 3) as Effect, e2 = countAt(tl, c2.id, 4) as Effect;
  const r = removeCounter(tl, [e1, e2], c1.id);
  assert.equal(r.timeline.counters!.length, 3);
  assert.deepEqual(r.effects.map((e) => e.counter), [c2.id]);
});

test("the tally lists the callout cards before it and the counter's total then", () => {
  let tl = base(); let fx: Effect[] = [];
  for (const [t, n] of [[3, "A"], [6, "B"], [20, "Late"]] as [number, string][]) {
    const r = addCount(tl, fx, t, n, "how");
    if ("error" in r) throw new Error(r.error);
    tl = r.timeline; fx = r.effects;
  }
  tl = ok(updateCounter(tl, tl.counters![0].id, { start_value: 10 }));
  const t = ok(addTitle(tl, "tally", 15));
  const tally = t.titles!.find((x) => x.template === "tally")!;
  const info = tallyInfo(t, fx, tally);
  assert.deepEqual(info.entries.map((e) => e[0]), ["A", "B"]);
  assert.equal(info.total, 12);
});

test("combos add several effects at the playhead in one go", () => {
  const tl = base();
  for (const c of COMBOS) {
    const made = c.make(tl, 7);
    assert.ok(made.length >= 2, c.id);
    assert.ok(made.every((e) => e.media_id === A.id && Math.abs(e.source_time - 7) < 1e-3), c.id);
  }
  const bass = COMBOS.find((c) => c.id === "bass_boosted")!.make(tl, 7);
  assert.ok(bass.some((e) => e.kind === "bass" && e.intensity === 1));
  assert.deepEqual(COMBOS[0].make(empty(), 1), []);
});

test("keep only the funny moments cuts everything else, moments back to back", () => {
  const tl = base();
  const out = ok(keepOnly(tl, [[40, 50], [10, 15], [12, 18]]));       // overlapping moments merge
  assert.ok(Math.abs(timelineDuration(out) - 18) < 1e-6);
  const v1 = [...out.tracks[0].clips].sort((a, b) => a.start - b.start);
  assert.deepEqual(v1.map((c) => [+c.start.toFixed(3), +c.source_in.toFixed(3), +c.source_out.toFixed(3)]), [[0, 10, 18], [8, 40, 50]]);
  assert.ok("error" in keepOnly(tl, []));
  assert.ok("error" in keepOnly(tl, [[0, 60]]));
});

test("who's talking: each recording's talking mapped through the clips (speed and trims)", () => {
  let tl = base();
  tl = ok(splitAt(tl, tl.tracks.flatMap((t) => t.clips.map((c) => c.id)), 20));
  tl = ok(cutRanges(tl, [[20, 30]]));
  const talk = { [A.id]: [[5, 8], [18, 25], [32, 33]] as [number, number][] };
  const iv = trackTalk(tl.tracks[1], talk).map(([a, b]) => [+a.toFixed(3), +b.toFixed(3)]);
  assert.deepEqual(iv, [[5, 8], [18, 20], [22, 23]]);                 // 20-30 s of the recording was cut
  const fast = { ...tl, tracks: tl.tracks.map((t) => ({ ...t, clips: t.clips.map((c) => ({ ...c, speed: 2 })) })) };
  assert.deepEqual(trackTalk({ ...fast.tracks[1], clips: [fast.tracks[1].clips[0]] }, talk).map(([a, b]) => [a, b]), [[2.5, 4], [9, 10]]);
});

test("tracks: narration role and name tags", () => {
  const tl = base();
  const n = ok(setTrackRole(tl, id(12), "narration"));
  assert.equal(n.tracks[1].role, "narration");
  assert.equal(ok(setTrackRole(tl, id(10), "narration")).tracks[0].role, undefined);    // video tracks don't have one
  const t = ok(setTrackTag(tl, id(12), "Riley the Great Destroyer of Worlds", "#ff0000"));
  assert.equal(t.tracks[1].tag, "Riley the Great Destroye"); assert.equal(t.tracks[1].tag_color, "#ff0000");
  assert.ok("error" in setTrackTag(tl, id(12), "x", "blue"));
});

test("text styles: presets apply, values are clamped, colours checked, a title's style can be saved", () => {
  let tl = ok(addTitle(base(), "pop_text", 1));
  const tid = tl.titles![0].id;
  for (const p of TEXT_PRESETS) {
    const r = ok(updateTitle(tl, tid, applyStyle(p)));
    assert.equal(r.titles![0].font, p.font);
    assert.ok(!("name" in r.titles![0]));
  }
  tl = ok(updateTitle(tl, tid, { stroke: 99, shadow: -3, glow: 100, number: 5000.6 }));
  assert.deepEqual([tl.titles![0].stroke, tl.titles![0].shadow, tl.titles![0].glow, tl.titles![0].number], [24, 0, 40, 999]);
  assert.ok("error" in updateTitle(tl, tid, { glow_color: "yellow" }));
  const s = styleOf(tl.titles![0], "Mine");
  assert.equal(s.name, "Mine"); assert.equal(s.stroke, 24);
  // new templates have sensible defaults
  for (const tpl of ["sticker", "count_card", "number_card", "tally"] as const) {
    const t = ok(addTitle(base(), tpl, 0)).titles![0];
    assert.ok(t.text.length > 0, tpl);
  }
});
