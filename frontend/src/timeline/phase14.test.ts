// Phase 14: background music for a stretch of time.
import { test } from "node:test";
import assert from "node:assert/strict";
import { addMedia, addMusic, clipEnd, cutRanges, deleteClips, LOOP_JOIN_FADE, MUSIC_DEFAULTS, musicItems, setMusicVolume, videoEnd } from "./ops";
import type { MediaAsset, Timeline } from "./types";

const id = (n: number) => n.toString(16).padStart(32, "0");
const asset = (n: number, kind: "video" | "audio", duration: number, has_audio = true): MediaAsset => ({
  id: id(n), original_name: kind === "audio" ? `song${n}.mp3` : `clip${n}.mp4`, stored_name: "x", kind, duration,
  size_bytes: 1, container: "mp4", has_video: kind === "video", has_audio, variable_frame_rate: false, imported_at: "",
});
const VID = asset(1, "video", 60), SONG = asset(2, "audio", 25), SILENT = asset(3, "video", 10, false);
const base = (): Timeline => {
  const tl: Timeline = { tracks: [
    { id: id(10), kind: "video", name: "V1", muted: false, hidden: false, locked: false, clips: [] },
    { id: id(12), kind: "audio", name: "A1", muted: false, hidden: false, locked: false, clips: [] },
  ] };
  return (addMedia(tl, VID) as any).timeline;
};
const ok = (r: any): Timeline => { assert.equal(r.error, undefined, r.error); return r.timeline; };
const music = (tl: Timeline) => tl.tracks.filter((t) => t.role === "music");

test("a song shorter than the stretch loops, with fades, on a new Music track", () => {
  const tl = ok(addMusic(base(), SONG, 5, 60));
  const [m] = music(tl);
  assert.equal(m.name, "Music");
  assert.equal(m.kind, "audio");
  const c = m.clips;
  assert.deepEqual(c.map((x) => [x.start, x.source_in, x.source_out]), [[5, 0, 25], [30, 0, 25], [55, 0, 5]]);
  assert.equal(clipEnd(c[2]), 60);
  assert.ok(c.every((x) => x.volume === MUSIC_DEFAULTS.volume && x.link_id === null));
  assert.equal(c[0].fade_in, 1);
  assert.equal(c[0].fade_out, LOOP_JOIN_FADE);
  assert.equal(c[1].fade_in, LOOP_JOIN_FADE);
  assert.equal(c[2].fade_out, 2);
  const items = musicItems(tl);
  assert.equal(items.length, 1);
  assert.deepEqual([items[0].start, items[0].end, items[0].clips.length], [5, 60, 3]);
});

test("no loop, start song later, volume, short stretch", () => {
  const tl = ok(addMusic(base(), SONG, 0, 60, { ...MUSIC_DEFAULTS, loop: false, songStart: 10, volume: 0.5, fadeOut: 20 }));
  const [c] = music(tl)[0].clips;
  assert.deepEqual([c.start, c.source_in, c.source_out, c.volume], [0, 10, 25, 0.5]);
  assert.equal(c.fade_out, 7.5);                      // never more than half the piece
  const short = ok(addMusic(base(), SONG, 10, 12));
  assert.equal(music(short)[0].clips.length, 1);
  assert.equal(clipEnd(music(short)[0].clips[0]), 12);
});

test("refusals", () => {
  assert.match(addMusic(base(), SILENT, 0, 5).error!, /no sound/);
  assert.match(addMusic(base(), SONG, 5, 5.2).error!, /half a second/);
  assert.match(addMusic(base(), SONG, 5, 3).error!, /half a second/);
  assert.match(addMusic(base(), SONG, 0, 10, { ...MUSIC_DEFAULTS, songStart: 30 }).error!, /past the end/);
  assert.match(addMusic(base(), SONG, 0, 10, { ...MUSIC_DEFAULTS, volume: 3 }).error!, /Volume/);
  assert.match(addMusic(base(), asset(4, "audio", 0.6), 0, 3600).error!, /too short to loop/);
});

test("a second song reuses the music track when it's free there, else makes another", () => {
  let tl = ok(addMusic(base(), SONG, 0, 20));
  tl = ok(addMusic(tl, SONG, 30, 40));               // free after 20: same track
  assert.equal(music(tl).length, 1);
  assert.equal(musicItems(tl).length, 2);
  tl = ok(addMusic(tl, SONG, 10, 25));               // overlaps: a second music track
  assert.deepEqual(music(tl).map((t) => t.name), ["Music", "Music 2"]);
  assert.equal(musicItems(tl).length, 3);
});

test("volume for a whole looped item; remove it; music isn't the 'video end'", () => {
  let tl = ok(addMusic(base(), SONG, 0, 70));
  assert.equal(videoEnd(tl), 60);
  const it = musicItems(tl)[0];
  tl = ok(setMusicVolume(tl, it.clips.map((c) => c.id), 0.8));
  assert.ok(music(tl)[0].clips.every((c) => c.volume === 0.8));
  tl = ok(deleteClips(tl, musicItems(tl)[0].clips.map((c) => c.id), false));
  assert.equal(musicItems(tl).length, 0);
  assert.equal(tl.tracks[0].clips.length, 1);        // the video is untouched
});

test("cutting words out of the video trims the music instead of shifting it", () => {
  let tl = ok(addMusic(base(), SONG, 0, 60));
  tl = ok(cutRanges(tl, [[10, 20]]));
  assert.equal(videoEnd(tl), 50);
  const end = Math.max(...music(tl)[0].clips.map(clipEnd));
  assert.ok(end <= 50 + 1e-6, `music ends at ${end}`);
});
