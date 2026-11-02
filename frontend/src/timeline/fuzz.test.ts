// Randomized stress test for the editing engine.
// Runs thousands of random edits (seeded, so failures are reproducible) and checks
// invariants after every step. Also writes sample timelines so the backend can
// confirm it accepts everything the engine produces (scripts/crosscheck.py).
import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdirSync, writeFileSync } from "node:fs";
import {
  MIN_CLIP, addMedia, addTrack, clipDuration, clipEnd, deleteClips, duplicateClip, moveClip, removeTrack,
  splitAt, timelineDuration, toggleTrack, trimEdge, updateClip, type OpResult,
} from "./ops";
import type { MediaAsset, MediaMap, Timeline } from "./types";

function rng(seed: number) {
  return () => { seed = (seed * 1664525 + 1013904223) >>> 0; return seed / 2 ** 32; };
}
const hex = (n: number) => n.toString(16).padStart(32, "0");
const MEDIA: MediaAsset[] = [
  { id: hex(1), original_name: "av.mp4", stored_name: "a.mp4", kind: "video", duration: 12.5, size_bytes: 1, container: "mp4", has_video: true, has_audio: true, variable_frame_rate: false, imported_at: "" },
  { id: hex(2), original_name: "v.mp4", stored_name: "b.mp4", kind: "video", duration: 3.2, size_bytes: 1, container: "mp4", has_video: true, has_audio: false, variable_frame_rate: false, imported_at: "" },
  { id: hex(3), original_name: "a.wav", stored_name: "c.wav", kind: "audio", duration: 47.123, size_bytes: 1, container: "wav", has_video: false, has_audio: true, variable_frame_rate: false, imported_at: "" },
];
const M: MediaMap = Object.fromEntries(MEDIA.map((m) => [m.id, m]));
const EPS = 1e-6;

function fresh(): Timeline {
  return { tracks: [
    { id: hex(100), kind: "video", name: "V1", muted: false, hidden: false, locked: false, clips: [] },
    { id: hex(101), kind: "video", name: "V2", muted: false, hidden: false, locked: false, clips: [] },
    { id: hex(102), kind: "audio", name: "A1", muted: false, hidden: false, locked: false, clips: [] },
  ] };
}

export function checkInvariants(tl: Timeline, where: string) {
  const ids = new Set<string>();
  const links = new Map<string, { start: number; dur: number; speed: number; si: number }>();
  const trackIds = new Set<string>();
  for (const t of tl.tracks) {
    assert.ok(!trackIds.has(t.id), `${where}: duplicate track id`);
    trackIds.add(t.id);
    let prevEnd = -Infinity;
    for (const c of t.clips) {
      assert.ok(!ids.has(c.id), `${where}: duplicate clip id`);
      ids.add(c.id);
      assert.ok(/^[0-9a-f]{32}$/.test(c.id), `${where}: bad id`);
      const m = M[c.media_id];
      assert.ok(m, `${where}: unknown media`);
      assert.ok(t.kind === "video" ? m.has_video : m.has_audio, `${where}: media kind on wrong track`);
      assert.ok(c.start >= -EPS, `${where}: negative start ${c.start}`);
      assert.ok(c.source_in >= -EPS, `${where}: negative in`);
      assert.ok(c.source_out <= m.duration + 1e-4, `${where}: out ${c.source_out} > ${m.duration}`);
      assert.ok(clipDuration(c) >= MIN_CLIP - 1e-4, `${where}: clip too short ${clipDuration(c)}`);
      assert.ok(c.speed >= 0.25 && c.speed <= 4, `${where}: speed`);
      assert.ok(c.start >= prevEnd - 1e-4, `${where}: overlap/unsorted on ${t.name} (${c.start} < ${prevEnd})`);
      prevEnd = clipEnd(c);
      if (c.link_id) {
        const k = links.get(c.link_id);
        const v = { start: c.start, dur: clipDuration(c), speed: c.speed, si: c.source_in };
        if (k) {
          assert.ok(Math.abs(k.start - v.start) < 1e-4 && Math.abs(k.dur - v.dur) < 1e-4 && k.speed === v.speed
            && Math.abs(k.si - v.si) < 1e-4, `${where}: linked clips out of sync`);
        } else links.set(c.link_id, v);
      }
    }
  }
}

function allClips(tl: Timeline) { return tl.tracks.flatMap((t) => t.clips); }

test("random edit sequences (FUZZ_SEEDS, default 10 × 1500) keep every invariant", () => {
  const samples: Timeline[] = [];
  let applied = 0, rejected = 0;
  const seeds = Number((globalThis as any).process?.env?.FUZZ_SEEDS ?? 10);
  for (let seed = 1; seed <= seeds; seed++) {
    const r = rng(seed);
    const pick = <T,>(a: T[]) => a[Math.floor(r() * a.length)];
    let tl = fresh();
    for (let step = 0; step < 1500; step++) {
      const clips = allClips(tl);
      const c = clips.length ? pick(clips) : null;
      const dur = Math.max(1, timelineDuration(tl));
      const t = r() * dur * 1.2;
      const op = Math.floor(r() * 12);
      let res: OpResult;
      switch (op) {
        case 0: res = addMedia(tl, pick(MEDIA), r() < 0.5 ? undefined : t, pick(tl.tracks).id); break;
        case 1: res = c ? splitAt(tl, [c.id], t) : { error: "none" }; break;
        case 2: res = c ? trimEdge(tl, c.id, r() < 0.5 ? "start" : "end", t, M) : { error: "none" }; break;
        case 3: res = c ? moveClip(tl, c.id, t, r() < 0.3 ? pick(tl.tracks).id : undefined) : { error: "none" }; break;
        case 4: res = c ? deleteClips(tl, [c.id], r() < 0.5) : { error: "none" }; break;
        case 5: res = c ? duplicateClip(tl, c.id) : { error: "none" }; break;
        case 6: res = c ? updateClip(tl, c.id, { speed: pick([0.25, 0.5, 1, 1.5, 2, 4, 5]) }) : { error: "none" }; break;
        case 7: res = c ? updateClip(tl, c.id, { volume: r() * 5, transform: { scale: r() * 3 + 0.05, x: r() * 400 - 200 } }) : { error: "none" }; break;
        case 8: res = toggleTrack(tl, pick(tl.tracks).id, pick(["muted", "hidden", "locked"] as const)); break;
        case 9: res = addTrack(tl, r() < 0.5 ? "video" : "audio"); break;
        case 10: res = removeTrack(tl, pick(tl.tracks).id); break;
        default: res = c ? splitAt(tl, allClips(tl).filter(() => r() < 0.3).map((x) => x.id), t) : { error: "none" };
      }
      if (res.error !== undefined) { rejected++; assert.equal(res.timeline, undefined); continue; }
      applied++;
      tl = res.timeline;
      checkInvariants(tl, `seed ${seed} step ${step} op ${op}`);
      if (allClips(tl).length > 150) tl = fresh(); // keep runtime bounded
    }
    samples.push(tl);
  }
  assert.ok(applied > 5000, `too few successful edits (${applied}); fuzzer is not exercising the engine`);
  mkdirSync(".test-build", { recursive: true });
  writeFileSync(".test-build/fuzz_timelines.json", JSON.stringify({ media: MEDIA, timelines: samples }));
  console.log(`# fuzz: ${applied} edits applied, ${rejected} correctly rejected`);
});

test("rejected edits never mutate input (immutability)", () => {
  const r = rng(99);
  let tl = fresh();
  for (let i = 0; i < 30; i++) { const x = addMedia(tl, MEDIA[i % 3]); if (x.timeline) tl = x.timeline; }
  const snapshot = JSON.stringify(tl);
  for (let i = 0; i < 2000; i++) {
    const c = allClips(tl)[Math.floor(r() * allClips(tl).length)];
    moveClip(tl, c.id, r() * 100); trimEdge(tl, c.id, "end", r() * 100, M); splitAt(tl, [c.id], r() * 100);
    deleteClips(tl, [c.id], true); updateClip(tl, c.id, { speed: 3 }); duplicateClip(tl, c.id);
  }
  assert.equal(JSON.stringify(tl), snapshot);
});
