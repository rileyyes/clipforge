import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { smoothJumpCuts, type JumpCutMode } from "./ops";
import type { Timeline } from "./types";

// the same cases the backend checks (backend/tests/data/jumpcut_vectors.json)
const cases = JSON.parse(readFileSync(new URL("../../../backend/tests/data/jumpcut_vectors.json", import.meta.url), "utf8"));

const summary = (tl: Timeline) => {
  const v = tl.tracks.find((t) => t.kind === "video")!;
  return [...v.clips].sort((a, b) => a.start - b.start).map((c) => [(c.crop?.left ?? 0) > 0, c.transition_in?.kind ?? null]);
};

for (const c of cases) {
  test(`jump cuts match the backend: ${c.name}`, () => {
    const tl = c.timeline as Timeline;
    for (const [mode, exp] of Object.entries(c.expect) as [JumpCutMode, { summary: unknown; count: number }][]) {
      const r = smoothJumpCuts(tl, mode);
      assert.ok(r.timeline, r.error);
      assert.deepEqual(summary(r.timeline!), exp.summary, mode);
      assert.equal(r.count, exp.count);
      const again = smoothJumpCuts(r.timeline!, mode);
      assert.deepEqual(summary(again.timeline!), exp.summary);
      const off = smoothJumpCuts(r.timeline!, "off");
      assert.deepEqual(summary(off.timeline!), summary(smoothJumpCuts(tl, "off").timeline!));
    }
  });
}
