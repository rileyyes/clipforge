// Caption lines for the preview: the same grouping as the export (backend/app/effects.py
// caption_chunks), checked against backend/tests/data/caption_vectors.json.
import { editWords, type Word } from "./cleanup";
import { effectWindows } from "./effects";
import type { CaptionSettings, Effect, Timeline } from "./types";

export interface CapWord { text: string; start: number; end: number }
export interface CapChunk { start: number; end: number; text: string; words: CapWord[] }

const isLetter = (ch: string) => /\p{L}/u.test(ch) || ch === "*";

/** "shit" -> "s***" (as the export masks bleeped words). */
export function maskWord(word: string): string {
  const chars = [...word];
  const letters = chars.flatMap((ch, i) => (isLetter(ch) ? [i] : []));
  if (letters.length <= 1) return "*".repeat(chars.length);
  for (const i of letters.slice(1)) chars[i] = "*";
  return chars.join("");
}

const pyUpper = (s: string) => s.toUpperCase();

/** Group the edit's words into short caption lines (bleeped words masked). */
export function captionChunks(tl: Timeline, effects: Effect[], byMedia: Record<string, Word[]>,
  cs: Pick<CaptionSettings, "max_words" | "uppercase">): CapChunk[] {
  const words = editWords(tl, byMedia).map((w) => ({ ...w }));
  const censor = effects.filter((e) => e.kind === "censor" && e.enabled !== false)
    .flatMap((e) => effectWindows(tl, e, "audio").map((w) => [w.start, w.end] as const));
  for (const w of words) {
    const mid = (w.start + w.end) / 2;
    if (censor.some(([a, b]) => a - 0.02 <= mid && mid <= b + 0.02)) w.text = maskWord(w.text.trim());
  }
  const chunks: { words: CapWord[] }[] = [];
  let cur: CapWord[] = [];
  for (const w of words) {
    const txt = w.text.trim();
    if (!txt) continue;
    const last = cur[cur.length - 1];
    if (last && (cur.length >= cs.max_words || w.start - last.end > 0.6 || ".?!".includes(last.text.trim().slice(-1) || "x"))) {
      chunks.push({ words: cur });
      cur = [];
    }
    cur.push({ text: cs.uppercase ? pyUpper(txt) : txt, start: w.start, end: w.end });
  }
  if (cur.length) chunks.push({ words: cur });
  return chunks.map((c, i) => {
    const start = c.words[0].start;
    let end = c.words[c.words.length - 1].end + 0.25;
    if (i + 1 < chunks.length) end = Math.min(end, chunks[i + 1].words[0].start);
    return { start, end: Math.max(end, start + 0.3), text: c.words.map((w) => w.text).join(" "), words: c.words };
  });
}

/** The caption line on screen at time t, and (for word highlight) which word is lit. */
export function captionAt(chunks: CapChunk[], t: number): { chunk: CapChunk; word: number } | null {
  const chunk = chunks.find((c) => t >= c.start && t < c.end);
  if (!chunk) return null;
  let word = 0;
  for (let i = 1; i < chunk.words.length; i++) if (t >= chunk.words[i].start) word = i;
  return { chunk, word };
}

// ---------------------------------------------------------------- Phase 19: key words
/** Same list and rule as backend/app/effects.py key_word (checked against tests/data/emphasis_vectors.json). */
const EMPHASIS_SKIP = new Set(["about", "above", "actually", "after", "again", "against", "almost", "already", "always", "another", "anything", "anyway", "around", "basically", "because", "before", "being", "below", "between", "could", "didn't", "doesn't", "during", "every", "everything", "going", "gonna", "gotta", "haven't", "literally", "little", "maybe", "might", "never", "nothing", "other", "probably", "really", "right", "should", "something", "sometimes", "still", "that's", "their", "there", "there's", "these", "they're", "thing", "things", "think", "those", "though", "through", "today", "together", "under", "until", "wanna", "we're", "what's", "where", "which", "while", "would", "yeah", "you're"]);
const isAlpha = (w: string) => /^[\p{L}]+$/u.test(w);
/** Which word of a caption line stands out: a number/amount first, else the longest 5+ letter
 *  word that isn't a filler word; first wins a tie; null if none. */
export function keyWord(texts: string[]): number | null {
  let best: number | null = null, score = 0;
  texts.forEach((t, i) => {
    if (t.includes("*")) return;
    const w = t.trim().replace(/^[.,!?;:"'()\[\]]+|[.,!?;:"'()\[\]]+$/g, "").toLowerCase();
    let sc = 0;
    if (/\d/.test(w) || w.includes("$") || w.includes("%")) sc = 100 + [...w].length;
    else if ([...w].length >= 5 && isAlpha(w.replace(/'/g, "")) && !EMPHASIS_SKIP.has(w)) sc = [...w].length;
    if (sc > score) { best = i; score = sc; }
  });
  return best;
}
