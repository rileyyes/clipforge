// The preview's captions are grouped exactly like the export's (backend/tests/data/caption_vectors.json).
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { captionAt, captionChunks, keyWord, maskWord } from "./captions";

const cases = JSON.parse(readFileSync(new URL("../../../backend/tests/data/caption_vectors.json", import.meta.url), "utf8"));

for (const c of cases) {
  test(`captions match the export: ${c.name}`, () => {
    const got = captionChunks(c.timeline, c.effects, c.words, c.captions)
      .map((x) => ({ start: +x.start.toFixed(6), end: +x.end.toFixed(6), text: x.text }));
    assert.deepEqual(got, c.expect);
  });
}

test("maskWord matches the export", () => {
  assert.equal(maskWord("shit"), "s***");
  assert.equal(maskWord("don't"), "d**'*");
  assert.equal(maskWord("a"), "*");
  assert.equal(maskWord("CAFÉ"), "C***");
});

test("captionAt finds the line and the lit word", () => {
  const ch = captionChunks(cases[0].timeline, [], cases[0].words, { max_words: 4, uppercase: false });
  assert.equal(captionAt(ch, 0.1), null);
  const a = captionAt(ch, 0.5)!;
  assert.equal(a.chunk.text, "So today we're going");
  assert.equal(a.word, 1);
  assert.equal(captionAt(ch, 1.1)!.word, 3);
});

test("key words: same choice as the backend (tests/data/emphasis_vectors.json)", () => {
  const v = JSON.parse(readFileSync(new URL("../../../backend/tests/data/emphasis_vectors.json", import.meta.url), "utf8"));
  assert.ok(v.cases.length >= 10);
  for (const c of v.cases) assert.equal(keyWord(c.words), c.key, JSON.stringify(c.words));
});
