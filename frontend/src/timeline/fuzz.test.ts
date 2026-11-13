// Randomized stress test for the editing engine.
// Runs thousands of random edits (seeded, so failures are reproducible) and checks
// invariants after every step. Also writes sample timelines so the backend can
// confirm it accepts everything the engine produces (scripts/crosscheck.py).
import { test } from "node:test";
import { applyLayout, insertFreeze, insertTeaser, RAMP_SLOWMO, RAMP_SPEEDUP, speedRamp } from "./pro";
import assert from "node:assert/strict";
import { mkdirSync, writeFileSync } from "node:fs";
import {
  MIN_CLIP, MUSIC_DEFAULTS, addMusic, addMarker, linkClips, moveClips, removeMarker, unlinkClips, addMedia, addTrack, clipDuration, clipEnd, deleteClips, duplicateClip, moveClip, removeTrack,
  addBlur, addTitle, cutRanges, fitMusicToVideo, snapCutsToBeats, removeBlur, updateBlur, removeTitle, sanitize, TITLE_TEMPLATES, updateTitle, setFades, smoothJumpCuts, setTrackRole, setTransition, splitAt, timelineDuration, toggleTrack, trimEdge, updateClip, type OpResult,
} from "./ops";
import { setKeyframe } from "./keyframes";
import { addCounter, keepOnly, updateCounter } from "./phase18";
import { slowPush } from "./phase19";
import { resetMix, setBlend, setTrackMix } from "./phase20";
import { setTrackTag } from "./ops";
import { BLEND_MODES, LOOKS, TRANSITIONS, type KfProp, type MediaAsset, type MediaMap, type Timeline } from "./types";

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
  const links = new Map<string, { start: number; dur: number; speed: number; si: number; media: string }>();
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
      assert.ok((c.fade_in ?? 0) + (c.fade_out ?? 0) <= clipDuration(c) + 1e-4, `${where}: fades longer than clip`);
      if (c.transition_in) {
        assert.equal(t.kind, "video", `${where}: transition on audio clip`);
        assert.ok(c.transition_in.duration <= clipDuration(c) * 0.9 + 1e-4 && c.transition_in.duration >= 0.1 - 1e-9, `${where}: transition too long`);
        const prev = t.clips.find((x) => x.id !== c.id && Math.abs(clipEnd(x) - c.start) < 0.02);
        if (prev) assert.ok(c.transition_in.duration <= clipDuration(prev) * 0.9 + 1e-4, `${where}: transition longer than previous clip`);
      }
      if (c.link_id) {
        const k = links.get(c.link_id);
        const v = { start: c.start, dur: clipDuration(c), speed: c.speed, si: c.source_in, media: c.media_id };
        if (k) {
          // same file: same part of it too (separately linked files only need to line up)
          assert.ok(Math.abs(k.start - v.start) < 1e-4 && Math.abs(k.dur - v.dur) < 1e-4 && k.speed === v.speed
            && (k.media !== v.media || Math.abs(k.si - v.si) < 1e-4), `${where}: linked clips out of sync`);
        } else links.set(c.link_id, v);
      }
    }
  }
}

function checkMarkers(tl: Timeline, where: string) {
  const ms = tl.markers ?? [];
  assert.ok(ms.every((m, i) => m.t >= 0 && /^[0-9a-f]{32}$/.test(m.id) && (i === 0 || ms[i - 1].t <= m.t)), `${where}: markers unsorted/invalid`);
  assert.equal(new Set(ms.map((m) => m.id)).size, ms.length, `${where}: duplicate marker id`);
  // Phase 18: same limits as the backend schema (scripts/crosscheck.py validates the samples there too)
  const cs = tl.counters ?? [];
  assert.ok(cs.length <= 4 && new Set(cs.map((c) => c.id)).size === cs.length, `${where}: counters`);
  for (const c of cs) assert.ok(c.label.length <= 24 && c.start_value >= 0 && c.start_value <= 9999 && Number.isInteger(c.start_value)
    && c.size >= 0.5 && c.size <= 2 && c.x >= 0 && c.x <= 1 && c.y >= 0 && c.y <= 1 && (c.end === null || c.end > c.start), `${where}: counter ${JSON.stringify(c)}`);
  for (const t of tl.titles ?? []) assert.ok((t.stroke == null || (t.stroke >= 0 && t.stroke <= 24)) && (t.shadow == null || (t.shadow >= 0 && t.shadow <= 24))
    && (t.glow ?? 0) >= 0 && (t.glow ?? 0) <= 40 && (t.number ?? 1) >= 0 && (t.number ?? 1) <= 999, `${where}: title style`);
  for (const t of tl.titles ?? []) assert.ok((t.points ?? []).length <= 20 && (t.points ?? []).every(([x, y]) => x >= 0 && x <= 1 && y >= 0 && y <= 1)
    && (t.w ?? 0.4) >= 0.01 && (t.w ?? 0.4) <= 1 && (t.h ?? 0.08) >= 0.01 && (t.h ?? 0.08) <= 1
    && Math.abs(t.count_from ?? 0) <= 1e9 && Math.abs(t.count_to ?? 0) <= 1e9, `${where}: title phase 19 fields`);
  for (const tr of tl.tracks) assert.ok((tr.volume ?? 1) >= 0 && (tr.volume ?? 1) <= 2 && (tr.kind === "audio" || (tr.volume === undefined && !tr.solo)), `${where}: track mix`);
  for (const c of allClips(tl)) assert.ok(!c.blend || (BLEND_MODES as readonly string[]).includes(c.blend), `${where}: blend ${c.blend}`);
  for (const tr of tl.tracks) assert.ok((tr.tag ?? "").length <= 24 && (!tr.tag_color || /^#[0-9a-fA-F]{6}$/.test(tr.tag_color)), `${where}: tag`);
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
      const op = Math.floor(r() * 40);
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
        case 12: res = c ? setTransition(tl, c.id, r() < 0.2 ? null : { kind: pick(TRANSITIONS.map((x) => x[0])), duration: 0.1 + r() * 2.9 }) : { error: "none" }; break;
        case 13: res = c ? setFades(tl, c.id, r() * 4, r() * 4) : { error: "none" }; break;
        case 15: { // keyframes, mostly the way the inspector makes them, sometimes raw/hostile
          if (!c) { res = { error: "none" }; break; }
          const prop = pick(["scale", "x", "y", "rotation", "opacity", "volume"] as KfProp[]);
          const at = c.source_in + r() * (c.source_out - c.source_in);
          const cur = c.keyframes?.[prop];
          const list = r() < 0.85 ? setKeyframe(cur, prop, at, (r() - 0.3) * 4, pick(["linear", "ease", "hold", undefined]))
            : r() < 0.5 ? [{ t: at, v: 1 }, { t: at, v: 2 }] : [{ t: at + 1, v: 0.5 }, { t: at, v: 0.5 }, { t: at, v: 99999 }];
          res = updateClip(tl, c.id, { keyframes: { [prop]: r() < 0.1 ? [] : list } });
          break;
        }
        case 16: res = c ? updateClip(tl, c.id, { crop: { left: r() * 0.6, right: r() * 0.6, top: r() * 0.5, bottom: r() * 0.5 },
          color: { brightness: r() - 0.5, contrast: r() * 2, saturation: r() * 3, gamma: 0.2 + r() * 3, temperature: r() * 2 - 1, look: pick([...LOOKS]) } }) : { error: "none" }; break;
        case 17: res = c ? updateClip(tl, c.id, { transform: { rotation: (r() - 0.5) * 8000, opacity: r() * 1.3 - 0.1 } }) : { error: "none" }; break;
        case 11: {
          const n = 1 + Math.floor(r() * 3);
          res = r() < 0.75 ? cutRanges(tl, Array.from({ length: n }, () => { const a = r() * dur; return [a, a + r() * 3] as [number, number]; }))
            : smoothJumpCuts(tl, pick(["off", "punch", "blend", "whip"] as const));
          break;
        }
        case 14: res = setTrackRole(tl, pick(tl.tracks).id, r() < 0.5 ? "music" : "dialogue"); break;
        case 18: res = addTitle(tl, pick(TITLE_TEMPLATES.map((x) => x[0])), t); break;
        case 19: {
          const ts = tl.titles ?? [];
          res = ts.length ? (r() < 0.3 ? removeTitle(tl, pick(ts).id) : updateTitle(tl, pick(ts).id, { start: t - 2, duration: r() * 20, size: r() * 3,
            text: "x".repeat(Math.floor(r() * 120)), align: pick(["left", "center", "right"] as const) })) : { error: "none" };
          break;
        }
        case 20: res = addBlur(tl, t, { x: r() * 1.5 - 0.5, y: r() * 1.5 - 0.5, w: r() * 1.2, h: r() * 1.2 }, r() * 10); break;
        case 21: {
          const bs = tl.blurs ?? [];
          res = bs.length ? (r() < 0.3 ? removeBlur(tl, pick(bs).id) : updateBlur(tl, pick(bs).id, { start: t - 1, duration: r() * 30, strength: r() * 2,
            mode: pick(["blur", "pixelate", "black"] as const), keys: Array.from({ length: Math.floor(r() * 5) + 1 }, () => ({ t: r() * dur, x: r(), y: r(), w: r(), h: r() })) })) : { error: "none" };
          break;
        }
        case 22: res = r() < 0.7 ? snapCutsToBeats(tl, Array.from({ length: 40 }, (_, i) => i * (0.3 + r() * 0.4)), M, r() * 0.5)
          : fitMusicToVideo(tl, r() * 4); break;
        case 23: res = moveClips(tl, allClips(tl).filter(() => r() < 0.25).map((x) => x.id), (r() - 0.5) * 20); break;
        case 24: res = c ? unlinkClips(tl, [c.id]) : { error: "none" }; break;
        case 25: res = r() < 0.5 || !c ? linkClips(tl, allClips(tl).filter(() => r() < 0.15).map((x) => x.id))
          // clips that line up with c on other tracks (e.g. after an unlink): the useful case
          : linkClips(tl, [c.id, ...tl.tracks.flatMap((tr) => tr.clips.filter((x) => x.id !== c.id && Math.abs(x.start - c.start) < 1e-4
              && Math.abs(clipDuration(x) - clipDuration(c)) < 1e-4).slice(0, 1).map((x) => x.id))]); break;
        case 26: res = r() < 0.6 ? addMarker(tl, t) : (tl.markers?.length ? removeMarker(tl, pick(tl.markers).id) : { error: "none" }); break;
        case 27: res = addMusic(tl, pick(MEDIA), t, t + r() * 40, { ...MUSIC_DEFAULTS, crossfade: r() < 0.5 ? r() * 2 : 0, beats: r() < 0.5 ? Array.from({ length: 40 }, (_, i) => 0.3 + i * (0.35 + r() * 0.3)) : undefined, loop: r() < 0.7, songStart: r() < 0.3 ? r() * 5 : 0, volume: r() * 1.5 }); break;
        case 28: res = c ? insertFreeze(tl, c.id, t, { ...MEDIA[0], id: MEDIA[0].id, duration: 0.5 + r() * 3 }) : { error: "none" }; break;
        case 29: res = c ? speedRamp(tl, c.id, t, r() < 0.5 ? RAMP_SLOWMO : { ...RAMP_SPEEDUP, hold: r() * 3 + 0.2 }) : { error: "none" }; break;
        case 30: res = applyLayout(tl, t, 1280, 720, pick(["side_by_side", "top_bottom", "pip", "reset"] as const), pick(["tl", "tr", "bl", "br"] as const), 0.2 + r() * 0.3); break;
        case 31: { const a = r() * 30; res = insertTeaser(tl, a, a + 0.3 + r() * 6); break; }
        // Phase 18
        case 32: { const a = r() * 30; res = keepOnly(tl, [[a, a + r() * 8], [a + r() * 20, a + 10 + r() * 10]]); break; }
        case 33: res = r() < 0.5 ? addCounter(tl, pick(["COUNT", "SCORE", ""])) : (tl.counters?.length
          ? updateCounter(tl, pick(tl.counters).id, { start: r() * 20, end: r() < 0.5 ? null : r() * 40, x: r(), y: r(), size: r() * 3, start_value: r() * 20000 })
          : { error: "none" }); break;
        case 34: { const a = tl.tracks.filter((x) => x.kind === "audio");
          res = a.length ? (r() < 0.5 ? setTrackTag(tl, pick(a).id, "Player " + Math.floor(r() * 9), pick(["#ff0000", "#5865f2", "nope"]))
            : setTrackRole(tl, pick(a).id, pick(["dialogue", "music", "narration"] as const))) : { error: "none" }; break; }
        case 35: { const tid = (tl.titles ?? [])[0]?.id;
          res = tid ? updateTitle(tl, tid, { font: pick([null, "anton", "creepster"]), stroke: r() < 0.3 ? null : r() * 40, shadow: r() * 30 - 3,
            glow: r() * 60, number: r() * 2000, glow_color: pick(["#ffde00", "#00ff00"]) }) : addTitle(tl, pick(["sticker", "count_card", "number_card", "tally"] as const), t); break; }
        // Phase 19
        case 36: { const tid = (tl.titles ?? [])[0]?.id;
          res = tid && r() < 0.6 ? updateTitle(tl, tid, { count_from: (r() - 0.5) * 4e9, count_to: r() * 1e5, format: pick(["time", "money", "number"] as const),
            points: Array.from({ length: Math.floor(r() * 30) }, () => [r() * 1.4 - 0.2, r() * 1.4 - 0.2] as [number, number]), w: r() * 2 - 0.5, h: r() * 2 - 0.5,
            anim: pick(["words", "pop"] as const) })
            : addTitle(tl, pick(["ticker", "stamp", "route", "highlight"] as const), t, pick(["Timer", "Money ticker", undefined])); break; }
        case 37: res = c ? slowPush(tl, c.id, pick(["in", "out", "off"] as const)) : { error: "none" }; break;
        // Phase 20
        case 38: { const a = tl.tracks.filter((x) => x.kind === "audio");
          res = a.length ? (r() < 0.15 ? resetMix(tl) : setTrackMix(tl, pick(a).id, { volume: r() * 3 - 0.5, solo: r() < 0.3 ? r() < 0.5 : undefined }))
            : { error: "none" }; break; }
        case 39: res = c ? (r() < 0.5 ? setBlend(tl, [c.id], pick(["screen", "multiply", "softlight", "normal", "bogus"] as any))
          : updateClip(tl, c.id, { blend: pick(["overlay", "addition", "difference", "x"] as any) })) : { error: "none" }; break;
        default: res = c ? splitAt(tl, allClips(tl).filter(() => r() < 0.3).map((x) => x.id), t) : { error: "none" };
      }
      if (res.error !== undefined) { rejected++; assert.equal(res.timeline, undefined); continue; }
      applied++;
      tl = sanitize(res.timeline); // the editor runs this after every edit
      checkInvariants(tl, `seed ${seed} step ${step} op ${op}`);
      checkMarkers(tl, `seed ${seed} step ${step} op ${op}`);
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
