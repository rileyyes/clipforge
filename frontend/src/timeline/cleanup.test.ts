import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { findCleanups } from "./cleanup";

const cases = JSON.parse(readFileSync(new URL("../../../backend/tests/data/cleanup_vectors.json", import.meta.url), "utf8"));
for (const c of cases) {
  test(`fillers + retakes match the backend: ${c.name}`, () => {
    assert.deepEqual(findCleanups(c.words), c.expect);
  });
}

import { editWords, rangeForWords } from "./cleanup";
import type { Timeline } from "./types";

test("editWords maps words through cuts; rangeForWords takes the pause after", () => {
  const A = "a".repeat(32);
  const tl = { tracks: [{ id: "1".repeat(32), kind: "audio", name: "A1", muted: false, hidden: false, locked: false, clips: [
    { id: "2".repeat(32), media_id: A, start: 0, source_in: 1, source_out: 3, speed: 1, volume: 1 },
    { id: "3".repeat(32), media_id: A, start: 2, source_in: 5, source_out: 7, speed: 2, volume: 1 },
  ] }] } as unknown as Timeline;
  const words = [{ text: "zero", start: 0.2, end: 0.5 }, { text: "one", start: 1.2, end: 1.5 }, { text: "two", start: 2.5, end: 2.9 },
    { text: "cut", start: 4, end: 4.3 }, { text: "five", start: 5.5, end: 5.9 }];
  const ew = editWords(tl, { [A]: words });
  assert.deepEqual(ew.map((w) => [w.text, w.start, w.end]), [["one", 0.2, 0.5], ["two", 1.5, 1.9], ["five", 2.25, 2.45]]);
  assert.deepEqual(rangeForWords(ew, 1, 1), [1.5 - 0.02, 2.2]);
  assert.deepEqual(rangeForWords(ew, 2, 2), [2.23, 2.55]);
});
