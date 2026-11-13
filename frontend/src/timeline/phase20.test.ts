// Phase 20: sound mixer and blend modes.
import { test } from "node:test";
import assert from "node:assert/strict";
import { addMedia, RETIRED_TEMPLATES, TITLE_TEMPLATES, updateClip } from "./ops";
import { anySolo, canBlend, clampFx, cssBlend, fmtDb, resetMix, setBlend, setTrackMix, trackGain } from "./phase20";
import { BLEND_MODES, type MediaAsset, type Timeline } from "./types";

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
  { id: id(13), kind: "audio", name: "A2", muted: false, hidden: false, locked: false, clips: [], role: "music" },
] });
const tr = (tl: Timeline, name: string) => tl.tracks.find((t) => t.name === name)!;

test("mixer: track level, mute and solo decide what's heard", () => {
  let tl = empty();
  assert.equal(trackGain(tl, tr(tl, "A1")), 1);
  assert.equal(trackGain(tl, tr(tl, "V1")), 0);          // pictures have no level
  tl = ok(setTrackMix(tl, id(13), { volume: 0.3 }));
  assert.equal(trackGain(tl, tr(tl, "A2")), 0.3);
  tl = ok(setTrackMix(tl, id(13), { volume: 9 }));        // clamped like the server (0..2)
  assert.equal(tr(tl, "A2").volume, 2);
  tl = ok(setTrackMix(tl, id(13), { volume: NaN }));
  assert.equal(tr(tl, "A2").volume, 1);
  tl = ok(setTrackMix(tl, id(12), { solo: true }));
  assert.ok(anySolo(tl));
  assert.equal(trackGain(tl, tr(tl, "A1")), 1);
  assert.equal(trackGain(tl, tr(tl, "A2")), 0);           // not solo → not heard
  tl = ok(setTrackMix(tl, id(12), { muted: true }));
  assert.equal(trackGain(tl, tr(tl, "A1")), 0);           // mute beats solo
  assert.ok(setTrackMix(tl, id(10), { volume: 1 }).error);
  assert.ok(setTrackMix(tl, "nope", { volume: 1 }).error);
  tl = ok(resetMix(ok(setTrackMix(tl, id(13), { volume: 0.2 }))));
  assert.ok(!anySolo(tl) && tr(tl, "A2").volume === 1 && tr(tl, "A1").muted);   // mutes stay
});

test("mixer: dB labels and the effects level", () => {
  assert.equal(fmtDb(1), "0 dB");
  assert.equal(fmtDb(0.5), "−6 dB");
  assert.equal(fmtDb(2), "+6 dB");
  assert.equal(fmtDb(0), "off");
  assert.equal(clampFx(5), 2);
  assert.equal(clampFx(-1), 0);
  assert.equal(clampFx(0.33333), 0.333);
});

test("blend modes: only above the base track, same names as the export", () => {
  let tl = ok(addMedia(empty(), A, 0, id(10)));
  tl = ok(addMedia(tl, B, 2, id(11)));
  const base = tr(tl, "V1").clips[0].id, top = tr(tl, "V2").clips[0].id;
  assert.ok(!canBlend(tl, base) && canBlend(tl, top));
  tl = ok(setBlend(tl, [top], "screen"));
  assert.equal(tr(tl, "V2").clips[0].blend, "screen");
  assert.equal(tr(tl, "V1").clips[0].blend, undefined);
  assert.ok(setBlend(tl, [top], "dissolve" as any).error);
  assert.ok(setBlend(tl, [], "screen").error);
  const audio = tr(tl, "A1").clips[0]?.id;
  if (audio) assert.ok(setBlend(tl, [audio], "screen").error);
  tl = ok(updateClip(tl, top, { blend: "multiply" }));
  assert.equal(tr(tl, "V2").clips[0].blend, "multiply");
  assert.ok(updateClip(tl, top, { blend: "nope" as any }).error);
  // a hidden V1 makes V2 the base (as in the export)
  const hidden = { ...tl, tracks: tl.tracks.map((t) => (t.name === "V1" ? { ...t, hidden: true } : t)) };
  assert.ok(!canBlend(hidden, top));
  assert.equal(cssBlend("normal"), undefined);
  assert.equal(cssBlend(undefined), undefined);
  assert.equal(cssBlend("addition"), "plus-lighter");
  assert.equal(cssBlend("softlight"), "soft-light");
  for (const m of BLEND_MODES) if (m !== "normal") assert.ok(cssBlend(m), m);
});

test("the old counter titles are kept for old projects but not offered any more", () => {
  for (const t of ["count_card", "tally"]) {
    assert.ok(RETIRED_TEMPLATES.includes(t));
    assert.ok(TITLE_TEMPLATES.some((x) => x[0] === t));     // still has a name for old projects
  }
  const offered = TITLE_TEMPLATES.filter(([t]) => !RETIRED_TEMPLATES.includes(t)).map(([, l, p]) => `${l} ${(p as any).text ?? ""}`.toLowerCase());
  for (const w of ["count", "kill", "tally", "callout"]) assert.ok(!offered.some((l) => l.includes(w)), `${w}: ${offered}`);
});
