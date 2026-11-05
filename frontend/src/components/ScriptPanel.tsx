import React, { useEffect, useMemo, useRef, useState } from "react";
import { fmtTime, type Job } from "../api";
import { editWords, findCleanups, rangeForWords, type Word } from "../timeline/cleanup";
import type { Timeline } from "../timeline/types";
import { Icon, useToast } from "./ui";

/** Editor → Script: the edit as text. Select words and cut them; remove "um"s and retakes. */
export default function ScriptPanel({ projectId, timeline, playhead, playing, seek, onCut, jobs, openEffects }: {
  projectId: string; timeline: Timeline; playhead: number; playing: boolean; seek: (t: number) => void;
  onCut: (ranges: [number, number][], label: string) => boolean; jobs: Job[]; openEffects: () => void;
}) {
  const toast = useToast();
  const [byMedia, setByMedia] = useState<Record<string, Word[]> | null>(null);
  const [sel, setSel] = useState<[number, number] | null>(null);
  const drag = useRef<{ from: number; moved: boolean } | null>(null);
  const curRef = useRef<HTMLSpanElement | null>(null);
  const transcribed = jobs.filter((j) => j.kind === "transcribe" && j.status === "succeeded").length;

  useEffect(() => {
    fetch(`/api/projects/${projectId}/words`).then((r) => r.json()).then((d) => setByMedia(d.media ?? {})).catch(() => setByMedia({}));
  }, [projectId, transcribed]);

  const words = useMemo(() => (byMedia ? editWords(timeline, byMedia) : []), [timeline, byMedia]);
  const cleanups = useMemo(() => findCleanups(words), [words]);
  const fillers = cleanups.filter((c) => c.kind === "filler"), retakes = cleanups.filter((c) => c.kind === "retake");
  const mark = useMemo(() => {
    const m = new Map<number, "filler" | "retake">();
    for (const c of cleanups) for (let i = c.first; i <= c.last; i++) m.set(i, c.kind);
    return m;
  }, [cleanups]);
  const cur = words.findIndex((w, i) => playhead >= w.start && playhead < (words[i + 1]?.start ?? w.end));
  useEffect(() => { if (playing) curRef.current?.scrollIntoView({ block: "nearest" }); }, [cur, playing]);
  useEffect(() => setSel(null), [timeline]);

  const [a, b] = sel ? [Math.min(...sel), Math.max(...sel)] : [-1, -1];
  const cutSelection = () => {
    if (!sel) return;
    const r = rangeForWords(words, a, b);
    if (onCut([r], b > a ? `Cut ${b - a + 1} words` : `Cut “${words[a].text.trim()}”`)) {
      toast(`Cut ${fmtTime(r[1] - r[0])} — Ctrl+Z to undo`);
      setSel(null);
    }
  };

  if (byMedia === null) return <div className="pane-body muted">Loading the transcript…</div>;
  if (!words.length) {
    return (
      <div className="pane-body" style={{ display: "grid", gap: 8, alignContent: "start" }}>
        <h3 style={{ margin: 0 }}>Script</h3>
        <p className="muted" style={{ fontSize: 12, margin: 0 }}>
          Edit your video by editing its text: select words and cut them, and remove "um"s and repeated takes in one click.
          This needs a transcript of the speech.
        </p>
        <button className="btn sm" onClick={openEffects}><Icon name="music" size={13} />Transcribe speech (Effects tab)</button>
      </div>
    );
  }
  return (
    <div className="pane-body" style={{ display: "grid", gap: 10, alignContent: "start" }} data-testid="script-panel"
      tabIndex={0} onKeyDown={(e) => {
        if ((e.key === "Delete" || e.key === "Backspace") && sel) { e.preventDefault(); e.stopPropagation(); cutSelection(); }
        if (e.key === "Escape" && sel) { e.stopPropagation(); setSel(null); }
      }}>
      <div className="row" style={{ gap: 4, flexWrap: "wrap" }}>
        <button className="btn sm" disabled={!fillers.length} onClick={() => {
          if (onCut(fillers.map((c) => [c.start, c.end]), "Remove filler words")) toast(`Removed ${fillers.length} filler word${fillers.length === 1 ? "" : "s"} — Ctrl+Z to undo`);
        }}><Icon name="scissors" size={13} />Remove {fillers.length} filler word{fillers.length === 1 ? "" : "s"}</button>
        <button className="btn sm" disabled={!retakes.length} onClick={() => {
          if (onCut(retakes.map((c) => [c.start, c.end]), "Remove retakes")) toast(`Removed ${retakes.length} retake${retakes.length === 1 ? "" : "s"} — Ctrl+Z to undo`);
        }}><Icon name="scissors" size={13} />Remove {retakes.length} retake{retakes.length === 1 ? "" : "s"}</button>
      </div>
      <div className="dim" style={{ fontSize: 11 }}>
        Click a word to jump there. Drag (or click, then Shift+click) to select, then <b>Cut</b> or press Delete.
        <span className="script-filler"> fillers</span> and <span className="script-retake">retakes</span> are marked.
      </div>
      {sel && (
        <div className="row" style={{ gap: 6 }}>
          <button className="btn sm primary" onClick={cutSelection}><Icon name="scissors" size={13} />Cut {b - a + 1} word{b > a ? "s" : ""}</button>
          <button className="btn xs ghost" onClick={() => setSel(null)}>Cancel</button>
        </div>
      )}
      <div className="script-text" onMouseUp={() => { drag.current = null; }} onMouseLeave={() => { drag.current = null; }}>
        {words.map((w, i) => (
          <React.Fragment key={`${w.media_id}@${w.src_start}`}>
            {i > 0 && w.start - words[i - 1].end > 1.2 && <span className="script-gap" title={`${(w.start - words[i - 1].end).toFixed(1)} s pause`}> ⋯ </span>}
            <span ref={i === cur ? curRef : undefined} data-i={i}
              className={"script-word" + (i === cur ? " cur" : "") + (i >= a && i <= b ? " sel" : "") +
                (mark.get(i) === "filler" ? " script-filler" : mark.get(i) === "retake" ? " script-retake" : "")}
              onMouseDown={(e) => {
                e.preventDefault();
                if (e.shiftKey && sel) { setSel([sel[0], i]); return; }
                drag.current = { from: i, moved: false };
                setSel(null);
              }}
              onMouseEnter={() => { if (drag.current) { drag.current.moved = true; setSel([drag.current.from, i]); } }}
              onMouseUp={() => {
                const d = drag.current;
                if (d && !d.moved) { seek(w.start); setSel([i, i]); }
                drag.current = null;
              }}>{w.text.trim()}</span>{" "}
          </React.Fragment>
        ))}
      </div>
      {retakes.length > 0 && (
        <div style={{ display: "grid", gap: 4 }}>
          <div className="dim" style={{ fontSize: 11 }}>Retakes (the first try is removed, the later one kept)</div>
          {retakes.map((r, i) => (
            <div key={i} className="row" style={{ fontSize: 12, gap: 6 }}>
              <span className="mono">{fmtTime(r.start)}</span><span className="ellipsis grow script-retake">{r.text}</span>
              <button className="btn xs ghost" onClick={() => seek(r.start)}>Listen</button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
