import type { Timeline } from "./types";
// Filler words and retakes in a transcript. Same rules as backend/app/cleanup.py
// (both checked against backend/tests/data/cleanup_vectors.json).
export interface Word { text: string; start: number; end: number }
export interface Cleanup { kind: "filler" | "retake"; start: number; end: number; text: string; first: number; last: number }

export const FILLERS = new Set(["um", "umm", "uh", "uhh", "uhm", "er", "erm", "ah", "hmm", "hm", "mm", "mhm"]);
const WINDOW = 15, MAX_WORDS = 30;
const r3 = (v: number) => Math.round(v * 1000) / 1000;
export const norm = (t: string) => t.toLowerCase().replace(/[^a-z0-9']+/g, "");

export function findCleanups(words: Word[]): Cleanup[] {
  const toks = words.map((w) => norm(w.text));
  const cuts: Cleanup[] = [];
  toks.forEach((t, i) => {
    if (!FILLERS.has(t)) return;
    let a = words[i].start - 0.05;
    if (i > 0) a = Math.max(a, words[i - 1].end + 0.02);
    const b = i + 1 < words.length ? Math.max(words[i].end, words[i + 1].start - 0.06) : words[i].end + 0.05;
    cuts.push({ kind: "filler", start: r3(Math.min(a, words[i].start)), end: r3(b), text: words[i].text.trim(), first: i, last: i });
  });
  const real = toks.map((t, i) => (t && !FILLERS.has(t) ? i : -1)).filter((i) => i >= 0);
  let k = 0;
  while (k < real.length) {
    let found: number | null = null;
    for (const n of [5, 4, 3]) {
      if (k + n > real.length) continue;
      const seq = real.slice(k, k + n).map((x) => toks[x]).join(" ");
      for (let m = k + n; m < Math.min(real.length - n + 1, k + MAX_WORDS); m++) {
        if (words[real[m]].start - words[real[k]].start > WINDOW) break;
        if (real.slice(m, m + n).map((x) => toks[x]).join(" ") === seq) { found = m; break; }
      }
      if (found !== null) break;
    }
    if (found === null) { k++; continue; }
    const i = real[k], j = real[found];
    cuts.push({ kind: "retake", start: r3(words[i].start - 0.02), end: r3(words[j].start - 0.05),
      text: words.slice(i, j).map((w) => w.text.trim()).join(" "), first: i, last: j - 1 });
    k = found;
  }
  return cuts.filter((c) => !(c.kind === "filler" && cuts.some((r) => r.kind === "retake" && r.first <= c.first && c.first <= r.last)))
    .sort((x, y) => x.start - y.start);
}


export interface EditWord extends Word { media_id: string; src_start: number }

/** Transcript words that are in the edit, in timeline time — same rules as the backend's
 *  edit_words (unmuted audio tracks; a word counts where it starts; no duplicates). */
export function editWords(tl: Timeline, byMedia: Record<string, Word[]>): EditWord[] {
  const out: EditWord[] = [];
  const seen = new Set<string>();
  for (const t of tl.tracks) {
    if (t.kind !== "audio" || t.muted) continue;
    for (const c of [...t.clips].sort((a, b) => a.start - b.start)) {
      for (const w of byMedia[c.media_id] ?? []) {
        if (!(c.source_in <= w.start && w.start < c.source_out)) continue;
        const key = `${c.media_id}@${w.start}`;
        if (seen.has(key)) continue;
        seen.add(key);
        const ts = c.start + (w.start - c.source_in) / c.speed;
        const te = c.start + (Math.min(w.end, c.source_out) - c.source_in) / c.speed;
        out.push({ text: w.text, start: r3(ts), end: r3(Math.max(te, ts + 0.05)), media_id: c.media_id, src_start: w.start });
      }
    }
  }
  return out.sort((a, b) => a.start - b.start);
}

/** The stretch to cut for words i..j (inclusive): from just before the first to just
 *  before the next word, so the pause after them goes too and the rhythm stays natural. */
export function rangeForWords(words: Word[], i: number, j: number): [number, number] {
  const a = i > 0 ? Math.max(words[i].start - 0.02, words[i - 1].end + 0.01) : Math.max(0, words[i].start - 0.02);
  const b = j + 1 < words.length ? Math.max(words[j].end, words[j + 1].start - 0.05) : words[j].end + 0.1;
  return [r3(a), r3(b)];
}
