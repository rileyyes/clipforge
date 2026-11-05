import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { camAt, defaultFaceCam, layoutBox } from "./facecam";
import type { MediaAsset, Timeline } from "./types";

const cases = JSON.parse(readFileSync(new URL("../../../backend/tests/data/facecam_layout_vectors.json", import.meta.url), "utf8"));

test("face cam boxes match the backend (preview = export)", () => {
  for (const c of cases) {
    const b = layoutBox(c.fc, c.W, c.H, c.aspect);
    for (const k of ["x", "y", "w", "h"] as const) assert.ok(Math.abs(b[k] - c.box[k]) < 1e-5, `${c.fc.corner} ${k}: ${b[k]} vs ${c.box[k]}`);
  }
});

test("camAt follows cuts, offset, hidden and full ranges", () => {
  const M = "a".repeat(32), C = "b".repeat(32);
  const tl: Timeline = { tracks: [{ id: "1".repeat(32), kind: "video", name: "V1", muted: false, hidden: false, locked: false, clips: [
    { id: "2".repeat(32), media_id: M, start: 0, source_in: 1, source_out: 4, speed: 1, volume: 1 },
    { id: "3".repeat(32), media_id: M, start: 3, source_in: 6, source_out: 9, speed: 1, volume: 1 },
  ] }] } as any;
  const cam = { id: C, duration: 8 } as MediaAsset;
  const fc = { ...defaultFaceCam(C, M), offset: -0.5, hidden: [{ start: 2, end: 2.5 }], full: [{ start: 7, end: 8 }] };
  assert.equal(camAt(tl, fc, cam, 0.5)!.camTime, 1.0);         // main 1.5
  assert.equal(camAt(tl, fc, cam, 1.2), null);                   // main 2.2: hidden
  assert.ok(camAt(tl, fc, cam, 0.9)!.alpha < 1);                 // fading out before it
  assert.equal(camAt(tl, fc, cam, 3.5)!.camTime, 6.0);           // second clip: main 6.5
  assert.equal(camAt(tl, fc, cam, 4.5)!.full, true);             // main 7.5
  assert.equal(camAt(tl, fc, cam, 5.8), null);                   // main 8.8 -> cam 8.3: past its end
  assert.equal(camAt(tl, { ...fc, enabled: false }, cam, 0.5), null);
});
