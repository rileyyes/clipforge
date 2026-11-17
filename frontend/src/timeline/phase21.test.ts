// Phase 21: multicam on the timeline, motion graphics rules, auto colour, edit by typing.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { addMedia, addTitle, clipDuration, clipEnd, cutRanges, splitAt, timelineDuration, updateTitle } from "./ops";
import { angleAt, applyAutoColor, applyMulticam, barGrow, baseTrack, decimals, endScreenBoxes, fmtValue, listDelay, removeMulticam,
  ringFraction, ringValue, rollingTime, setClipAngle } from "./phase21";
import { parseCommand, parseTime, runCommand, splitLines, type Ctx } from "./commands";
import type { AudioSettings, MediaAsset, MediaMap, Multicam, Timeline } from "./types";

const id = (n: number) => n.toString(16).padStart(32, "0");
const asset = (n: number, duration: number, audio = true): MediaAsset => ({
  id: id(n), original_name: `m${n}.mp4`, stored_name: "x", kind: "video", duration, size_bytes: 1, container: "mp4",
  has_video: true, has_audio: audio, variable_frame_rate: false, imported_at: "",
});
const MAIN = asset(1, 60), CAMB = asset(2, 58, false), CAMC = asset(3, 30, false);
const media: MediaMap = { [MAIN.id]: MAIN, [CAMB.id]: CAMB, [CAMC.id]: CAMC };
const ok = (r: any): Timeline => { assert.equal(r.error, undefined, r.error); return r.timeline; };
const empty = (): Timeline => ({ tracks: [
  { id: id(10), kind: "video", name: "V1", muted: false, hidden: false, locked: false, clips: [] },
  { id: id(11), kind: "video", name: "V2", muted: false, hidden: false, locked: false, clips: [] },
  { id: id(12), kind: "audio", name: "A1", muted: false, hidden: false, locked: false, clips: [] },
  { id: id(13), kind: "audio", name: "A2", muted: false, hidden: false, locked: false, clips: [], role: "music" },
] });
const mc = (switches: [number, number][]): Multicam => ({
  main_media_id: MAIN.id, mode: "speaker", wide: null, min_shot: 2, pace: 5,
  angles: [{ media_id: MAIN.id, offset: 0 }, { media_id: CAMB.id, offset: -2 }, { media_id: CAMC.id, offset: 5 }],
  switches: switches.map(([t, angle]) => ({ t, angle })),
});
const v1 = (tl: Timeline) => tl.tracks[0].clips;
const a1 = (tl: Timeline) => tl.tracks[2].clips;

/** Every moment of the edit shows the same moment of the main recording (sound and picture in sync). */
function inSync(tl: Timeline, plan: Multicam) {
  const audio = a1(tl);
  for (const c of v1(tl)) {
    const i = plan.angles.findIndex((a) => a.media_id === c.media_id);
    assert.ok(i >= 0, "picture from a camera");
    const mainIn = c.source_in - plan.angles[i].offset;
    const a = audio.find((x) => Math.abs(x.start - c.start) < 1e-6);
    assert.ok(a, `sound under the shot at ${c.start}`);
    assert.ok(Math.abs(a!.source_in - mainIn) < 1e-4 && Math.abs(clipDuration(a!) - clipDuration(c)) < 1e-4, "same moment");
    assert.equal(a!.link_id, c.link_id);
  }
}

test("multicam: cuts the edit where the camera changes, keeps the cuts and the sound", () => {
  let tl = ok(addMedia(empty(), MAIN, 0, id(10)));
  tl = ok(cutRanges(tl, [[20, 30]]));                        // an edit: main 0-20, then main 30-60 at 20
  const plan = mc([[0, 0], [10, 1], [25, 2], [40, 0], [50, 1]]);
  const r = applyMulticam(tl, plan, media) as any;
  const out = ok(r);
  const shots = v1(out).map((c) => [c.start, c.media_id === MAIN.id ? 0 : c.media_id === CAMB.id ? 1 : 2]);
  // main time 25-30 was cut; cam C (offset 5) only goes to 25 main time, so 30-40 stays on main
  assert.deepEqual(shots, [[0, 0], [10, 1], [20, 0], [30, 0], [40, 1]]);
  assert.equal(out.multicam, plan);
  assert.ok(Math.abs(timelineDuration(out) - timelineDuration(tl)) < 1e-6);
  inSync(out, plan);
  // a camera clip's source = main time + offset
  const b = v1(out)[1];
  assert.equal(b.media_id, CAMB.id);
  assert.ok(Math.abs(b.source_in - 8) < 1e-6 && Math.abs(b.source_out - 18) < 1e-6);
  // applying again (new switches) starts from the main recording: no leftovers
  const plan2 = mc([[0, 1]]);
  const again = ok(applyMulticam(out, plan2, media));
  assert.ok(v1(again).every((c) => c.media_id === CAMB.id || c.source_in < 2));        // cam B everywhere it filmed (it started 2 s late)
  inSync(again, plan2);
  // back to one camera
  const one = ok(removeMulticam(again));
  assert.ok(v1(one).every((c) => c.media_id === MAIN.id) && one.multicam === null);
  inSync(one, plan2);
});

test("multicam: pick a camera by hand, and the errors", () => {
  let tl = ok(addMedia(empty(), MAIN, 0, id(10)));
  const plan = mc([[0, 0], [10, 1]]);
  tl = ok(applyMulticam(tl, plan, media));
  const first = v1(tl)[0].id, second = v1(tl)[1].id;
  const t2 = ok(setClipAngle(tl, first, 2, media));                  // cam C filmed main 0-10 (as its 5-15)
  assert.equal(v1(t2)[0].media_id, CAMC.id);
  assert.ok(setClipAngle(tl, second, 2, media).error);               // main 10-60 is beyond cam C's 30 s
  assert.ok(setClipAngle(empty(), first, 1, media).error);
  assert.ok(applyMulticam(empty(), plan, media).error);              // main recording not on V1
  assert.ok(applyMulticam(tl, { ...plan, angles: [plan.angles[1], plan.angles[0]] }, media).error);
  assert.equal(angleAt(plan, 9.99), 0);
  assert.equal(angleAt(plan, 10), 1);
  assert.equal(angleAt({ switches: [] }, 3), 0);
  // a hidden V1 is skipped (like the export)
  const hidden = { ...tl, tracks: tl.tracks.map((t, i) => (i === 0 ? { ...t, hidden: true } : t)) };
  assert.equal(baseTrack(hidden)?.name, "V2");
  // splits made later keep working: split a camera shot, its pieces stay on that camera
  const sp = ok(splitAt(tl, [second], 30));
  assert.ok(v1(sp).filter((c) => c.start >= 10).every((c) => c.media_id === CAMB.id));
});

// ---------------------------------------------------------------- motion graphics
const vec = JSON.parse(readFileSync(new URL("../../../backend/tests/data/motion_vectors.json", import.meta.url), "utf8"));

test("motion graphics follow the export's rules (shared vectors)", () => {
  for (const [tt, i, g] of vec.bar_grow) assert.ok(Math.abs(barGrow(tt, i) - g) < 1e-9, `bar ${tt} ${i}`);
  for (const [v, f, d, txt] of vec.fmt_value) assert.equal(fmtValue(v, f, d), txt, `${v} ${f} ${d}`);
  for (const [vals, d] of vec.decimals) assert.equal(decimals(vals), d, String(vals));
  for (const [t, tt, v, frac] of vec.ring) {
    assert.ok(Math.abs(ringValue(tt, t) - v) < 1e-9);
    assert.ok(Math.abs(ringFraction(v, t) - frac) < 1e-9);
  }
  for (const [i, n, dur, d] of vec.list_delay) assert.ok(Math.abs(listDelay(i, n, dur) - d) < 1e-9);
  const [W, H, videos, sub] = vec.end_screen;
  const b = endScreenBoxes(W, H);
  b.videos.forEach((v, i) => v.forEach((x, k) => assert.ok(Math.abs(x - videos[i][k]) < 1e-4)));
  b.subscribe.forEach((x, k) => assert.ok(Math.abs(x - sub[k]) < 1e-4));
  // rolling numbers change in steps like the export
  assert.equal(rollingTime(0.1, 0.25, 0.85), 0);
  assert.ok(Math.abs(rollingTime(0.5, 0.25, 0.85) - (0.25 + 3 * 0.6 / 9)) < 1e-9);
  assert.equal(rollingTime(5, 0.25, 0.85), 0.85);
});

test("motion graphics presets: progress bar spans the video, end screen sits at the end", () => {
  let tl = ok(addMedia(empty(), MAIN, 0, id(10)));
  const p = addTitle(tl, "progress", 12);
  tl = ok(p);
  const bar = tl.titles!.find((x) => x.id === p.id)!;
  assert.equal(bar.start, 0); assert.equal(bar.duration, 60);
  const e = addTitle(tl, "end_screen", 3);
  const es = ok(e).titles!.find((x) => x.id === e.id)!;
  assert.equal(es.start, 40); assert.equal(es.duration, 20);
  const c = addTitle(tl, "chart", 5);
  let t2 = ok(c);
  const chart = t2.titles!.find((x) => x.id === c.id)!;
  assert.equal(chart.items?.length, 3);
  // presets aren't shared between titles
  chart.items![0].label = "changed";
  const c2 = addTitle(tl, "chart", 5);
  assert.equal(ok(c2).titles!.find((x) => x.id === c2.id)!.items![0].label, "First");
  t2 = ok(updateTitle(t2, c.id!, { items: [...Array(12)].map((_, i) => ({ label: "x".repeat(50), value: i === 0 ? NaN : 1e12 })) }));
  const it = t2.titles!.find((x) => x.id === c.id)!.items!;
  assert.equal(it.length, 10); assert.equal(it[0].label.length, 40); assert.equal(it[0].value, 0); assert.equal(it[1].value, 1e9);
  assert.equal(ok(updateTitle(tl, p.id!, { duration: 99999 })).titles!.find((x) => x.id === p.id)!.duration, 14400);
  assert.equal(ok(updateTitle(t2, c.id!, { duration: 9999 })).titles!.find((x) => x.id === c.id)!.duration, 600);
});

// ---------------------------------------------------------------- auto colour
test("auto colour goes on every clip of that recording and keeps each look", () => {
  let tl = ok(addMedia(empty(), MAIN, 0, id(10)));
  tl = ok(splitAt(tl, [v1(tl)[0].id], 30));
  tl = { ...tl, tracks: tl.tracks.map((t, i) => (i === 0 ? { ...t, clips: t.clips.map((c, k) => (k === 1 ? { ...c, color: { brightness: 0, contrast: 1, saturation: 1, gamma: 1, temperature: 0, look: "vhs" as const } } : c)) } : t)) };
  const out = ok(applyAutoColor(tl, { [MAIN.id]: { brightness: 0.1, contrast: 1.2, saturation: 9, gamma: 1, temperature: 0.3, look: "none" } }));
  assert.ok(v1(out).every((c) => c.color!.brightness === 0.1 && c.color!.saturation === 3));
  assert.equal(v1(out)[1].color!.look, "vhs");
  assert.ok(applyAutoColor(tl, {}).error);
  assert.ok(applyAutoColor(tl, { [CAMB.id]: { brightness: 0, contrast: 1, saturation: 1, gamma: 1, temperature: 0, look: "none" } }).error);
});

// ---------------------------------------------------------------- edit by typing
const AUDIO: AudioSettings = { normalize: true, enhance_voice: false, ducking: "medium" } as AudioSettings;
function ctxOf(tl: Timeline, extra: Partial<Ctx> = {}): Ctx { return { timeline: tl, effects: [], audio: AUDIO, playhead: 12, selection: [], ...extra }; }
const P = { playhead: 12, end: 60 };

test("commands: times", () => {
  assert.equal(parseTime("1:05"), 65);
  assert.equal(parseTime("1:05.5"), 65.5);
  assert.equal(parseTime("0:01:05"), 65);
  assert.equal(parseTime("65s"), 65);
  assert.equal(parseTime("65 seconds"), 65);
  assert.equal(parseTime("1m 5s"), 65);
  assert.equal(parseTime("2 min"), 120);
  assert.equal(parseTime("here", P), 12);
  assert.equal(parseTime("the end", P), 60);
  assert.equal(parseTime("start"), 0);
  assert.equal(parseTime("soon"), null);
});

test("commands: understood", () => {
  const cases: [string, any][] = [
    ["cut 0:10 to 0:20", { kind: "cut", from: 10, to: 20 }],
    ["Delete from 1:00 to 1:30.", { kind: "cut", from: 60, to: 90 }],
    ["split at 0:30", { kind: "split", at: 30 }], ["split", { kind: "split", at: 12 }],
    ["go to 1:30", { kind: "go", at: 90 }],
    ["add a zoom at 1:05", { kind: "effect", effect: "zoom", at: 65 }], ["add a punch in", { kind: "effect", effect: "zoom", at: 12 }],
    ["add a screen shake at 5s", { kind: "effect", effect: "shake", at: 5 }],
    ["add a whoosh at 0:42", { kind: "sound", sound: "whoosh", at: 42 }], ["play the airhorn sound here", { kind: "sound", sound: "airhorn", at: 12 }],
    ['add text "NO WAY" at 0:30', { kind: "title", template: "pop_text", text: "NO WAY", at: 30 }],
    ['add a title "Chapter 2" at 2:00', { kind: "title", template: "big_title", text: "Chapter 2", at: 120 }],
    ["add a bar chart", { kind: "title", template: "chart", label: undefined, at: 12 }],
    ["add a timer at 0:05", { kind: "title", template: "ticker", label: "Timer", at: 5 }],
    ["add an end screen", { kind: "title", template: "end_screen", label: undefined, at: 12 }],
    ['add a marker "Intro" at 0:00', { kind: "marker", at: 0, label: "Intro" }],
    ["music to 30%", { kind: "volume", target: "music", value: 0.3 }], ["set the sound effects to 50%", { kind: "volume", target: "sound effects", value: 0.5 }],
    ["mute A2", { kind: "mute", target: "a2" }], ["solo the music", { kind: "solo", target: "music" }],
    ["blend soft light", { kind: "blend", mode: "softlight" }], ["blend add", { kind: "blend", mode: "addition" }],
    ["undo", { kind: "undo" }],
  ];
  for (const [line, want] of cases) assert.deepEqual(parseCommand(line, P), want, line);
  for (const bad of ["make it better", "cut 0:20 to 0:10", "music to 300%", "add a dragon", "blend sideways"])
    assert.ok("error" in parseCommand(bad, P), bad);
  assert.deepEqual(splitLines("add a zoom at 1:05; music to 30%\nthen go to 0:10"), ["add a zoom at 1:05", "music to 30%", "go to 0:10"]);
});

test("commands: run as normal edits", () => {
  let tl = ok(addMedia(empty(), MAIN, 0, id(10)));
  const run = (line: string, extra: Partial<Ctx> = {}) => {
    const c = parseCommand(line, { playhead: 12, end: timelineDuration(tl) });
    assert.ok(!("error" in c), line);
    return runCommand(c as any, ctxOf(tl, extra)) as any;
  };
  let r = run("cut 0:10 to 0:20");
  assert.equal(timelineDuration(r.timeline), 50);
  r = run("split at 0:30"); assert.equal(v1(r.timeline).length, 2);
  r = run("add a zoom at 0:05"); assert.equal(r.effects.length, 1); assert.equal(r.effects[0].kind, "zoom");
  r = run("add a whoosh at 0:05"); assert.equal(r.effects[0].sound, "whoosh");
  r = run('add text "WOW" at 0:05'); assert.equal(r.timeline.titles[0].text, "WOW");
  r = run('add a marker "Intro" at 0:00'); assert.equal(r.timeline.markers[0].label, "Intro");
  tl = { ...tl, tracks: tl.tracks.map((t) => (t.name === "A2" ? { ...t, clips: [{ ...a1(tl)[0], id: id(99), link_id: null }] } : t)) };
  r = run("music to 30%"); assert.equal(r.timeline.tracks[3].volume, 0.3);
  r = run("voice to 150%"); assert.equal(r.timeline.tracks[2].volume, 1.5);
  r = run("sound effects to 40%"); assert.equal(r.audio.fx_volume, 0.4);
  r = run("solo music"); assert.equal(r.timeline.tracks[3].solo, true);
  r = run("go to 0:30"); assert.equal(r.seek, 30);
  assert.ok(run("blend screen").error);                                   // nothing selected
  assert.ok(run("add a zoom at 9:00").error);                             // no footage there
  assert.ok(run("cut 5:00 to 6:00").error);
  assert.ok(run("mute A7").error);
});
