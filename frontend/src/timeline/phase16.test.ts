// Phase 16: beat-aligned music loops with real crossfades; teaser.
import { test } from "node:test";
import assert from "node:assert/strict";
import { addMedia, addMusic, clipEnd, MUSIC_DEFAULTS, musicItems } from "./ops";
import { insertTeaser } from "./pro";
import type { MediaAsset, Timeline } from "./types";

const id = (n: number) => n.toString(16).padStart(32, "0");
const asset = (n: number, kind: "video" | "audio", duration: number): MediaAsset => ({
  id: id(n), original_name: kind === "audio" ? "song.mp3" : "v.mp4", stored_name: "x", kind, duration, size_bytes: 1, container: "mp4",
  has_video: kind === "video", has_audio: true, variable_frame_rate: false, imported_at: "",
});
const VID = asset(1, "video", 120), SONG = asset(2, "audio", 30.3);
const ok = (r: any): Timeline => { assert.equal(r.error, undefined, r.error); return r.timeline; };
const base = (): Timeline => ok(addMedia({ tracks: [
  { id: id(10), kind: "video", name: "V1", muted: false, hidden: false, locked: false, clips: [] },
  { id: id(12), kind: "audio", name: "A1", muted: false, hidden: false, locked: false, clips: [] },
] }, VID));
// 120 bpm: a beat every 0.5 s, from 0.25 s
const BEATS = Array.from({ length: 60 }, (_, i) => 0.25 + i * 0.5);

test("crossfaded loop: whole bars from a beat, overlapping repeats on two tracks", () => {
  const tl = ok(addMusic(base(), SONG, 0, 100, { ...MUSIC_DEFAULTS, crossfade: 1.2, beats: BEATS, songStart: 1.0 }));
  const music = tl.tracks.filter((t) => t.role === "music");
  assert.equal(music.length, 2);
  const all = music.flatMap((t) => t.clips).sort((a, b) => a.start - b.start);
  // starts on the first beat at/after 1.0 s; loop length is whole bars (multiple of 4 beats = 2 s)
  assert.ok(all.every((c) => c.source_in === 1.25));
  const loopLen = all[0].source_out - all[0].source_in;
  assert.ok(Math.abs(loopLen / 2 - Math.round(loopLen / 2)) < 1e-6, `${loopLen}`);
  // crossfade rounded to whole beats (1.2 -> 1.0) and each repeat overlaps the one before by it
  for (let i = 1; i < all.length; i++) {
    assert.ok(Math.abs(clipEnd(all[i - 1]) - all[i].start - 1.0) < 1e-6, `overlap ${clipEnd(all[i - 1]) - all[i].start}`);
    assert.notEqual(all[i].id, all[i - 1].id);
    assert.equal(all[i].fade_in, 1.0);
    assert.equal(all[i - 1].fade_out, 1.0);
  }
  for (const t of music) for (let i = 1; i < t.clips.length; i++) assert.ok(t.clips[i].start >= clipEnd(t.clips[i - 1]) - 1e-6);
  assert.equal(clipEnd(all[all.length - 1]), 100);
  assert.equal(all[0].fade_in, 1);
  assert.equal(all[all.length - 1].fade_out, 2);
  const items = musicItems(tl);
  assert.equal(items.length, 1);                       // listed as one song
  assert.equal(items[0].clips.length, all.length);
  assert.deepEqual([items[0].start, items[0].end], [0, 100]);
});

test("crossfade without beats, and fallbacks", () => {
  const tl = ok(addMusic(base(), SONG, 0, 70, { ...MUSIC_DEFAULTS, crossfade: 1.5 }));
  const all = tl.tracks.filter((t) => t.role === "music").flatMap((t) => t.clips).sort((a, b) => a.start - b.start);
  assert.ok(Math.abs(clipEnd(all[0]) - all[1].start - 1.5) < 1e-6);
  // song longer than the stretch: no loop, one piece
  const one = ok(addMusic(base(), SONG, 0, 20, { ...MUSIC_DEFAULTS, crossfade: 1.5 }));
  assert.equal(one.tracks.filter((t) => t.role === "music").flatMap((t) => t.clips).length, 1);
  // song too short for a crossfade: the old dip join
  const tiny = asset(3, "audio", 2.5);
  const dip = ok(addMusic(base(), tiny, 0, 10, { ...MUSIC_DEFAULTS, crossfade: 1.5 }));
  assert.equal(dip.tracks.filter((t) => t.role === "music").length, 1);
});

test("teaser: a copy of a moment goes first, everything else moves later", () => {
  const tl = ok(insertTeaser(base(), 50, 54));
  const v = tl.tracks[0].clips, a = tl.tracks[1].clips;
  assert.deepEqual(v.map((c) => [c.start, c.source_in, c.source_out]), [[0, 50, 54], [4, 0, 120]]);
  assert.deepEqual(a.map((c) => [c.start, c.source_in]), [[0, 50], [4, 0]]);
  assert.ok(v[0].link_id && v[0].link_id === a[0].link_id && v[0].link_id !== v[1].link_id);
  assert.match(insertTeaser(base(), 50, 50.2).error!, /at least/);
  assert.match(insertTeaser(base(), 500, 504).error!, /nothing/i);
});
