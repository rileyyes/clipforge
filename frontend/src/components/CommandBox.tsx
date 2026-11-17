import React, { useRef, useState } from "react";
import { call } from "../api";
import { EXAMPLES, parseCommand, runCommand, splitLines, type Cmd, type Ctx, type Done } from "../timeline/commands";
import { timelineDuration } from "../timeline/ops";
import type { AudioSettings, Effect, Timeline } from "../timeline/types";
import { useToast } from "./ui";

/** Editor → AI → "Tell RJClip what to do" (Phase 21). Plain commands run straight away; with a
 *  free local AI (Ollama) running, other wording is turned into those commands first. Every
 *  change is one undo step. Press / anywhere in the editor to jump here. */
export default function CommandBox({ projectId, timeline, effects, audio, playhead, selection, apply, seek, undo, redo }: {
  projectId: string; timeline: Timeline; effects: Effect[]; audio: AudioSettings; playhead: number; selection: string[];
  apply: (d: { timeline?: Timeline; effects?: Effect[]; audio?: AudioSettings }, label: string) => void;
  seek: (t: number) => void; undo: () => void; redo: () => void;
}) {
  const toast = useToast();
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [log, setLog] = useState<{ ok: boolean; text: string }[]>([]);
  const [help, setHelp] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  /** Run every line on the same running state; apply once (one undo step). */
  const runLines = (lines: string[], via: string): boolean => {
    let ctx: Ctx = { timeline, effects, audio, playhead, selection };
    const msgs: string[] = [];
    const changed: { timeline?: Timeline; effects?: Effect[]; audio?: AudioSettings } = {};
    let goTo: number | null = null, labels: string[] = [];
    for (const line of lines) {
      const c = parseCommand(line, { playhead, end: timelineDuration(ctx.timeline) });
      if ("error" in c) { setLog((l) => [{ ok: false, text: `${line} — ${c.error}` }, ...l].slice(0, 8)); return false; }
      if ((c.kind === "undo" || c.kind === "redo") && lines.length > 1) { setLog((l) => [{ ok: false, text: "Undo/redo on its own line, please." }, ...l]); return false; }
      if (c.kind === "undo") { undo(); setLog((l) => [{ ok: true, text: "undo" }, ...l].slice(0, 8)); return true; }
      if (c.kind === "redo") { redo(); setLog((l) => [{ ok: true, text: "redo" }, ...l].slice(0, 8)); return true; }
      const r = runCommand(c as Cmd, ctx);
      if ("error" in r) { setLog((l) => [{ ok: false, text: `${line} — ${r.error}` }, ...l].slice(0, 8)); return false; }
      const d = r as Done;
      if (d.timeline) { changed.timeline = d.timeline; ctx = { ...ctx, timeline: d.timeline }; }
      if (d.effects) { changed.effects = d.effects; ctx = { ...ctx, effects: d.effects }; }
      if (d.audio) { changed.audio = d.audio; ctx = { ...ctx, audio: d.audio }; }
      if (d.seek !== undefined) goTo = d.seek;
      msgs.push(d.message); labels.push(d.label);
    }
    if (changed.timeline || changed.effects || changed.audio) apply(changed, labels.length === 1 ? labels[0] : `${labels.length} commands`);
    if (goTo !== null) seek(goTo);
    setLog((l) => [...msgs.map((m) => ({ ok: true, text: via + m })).reverse(), ...l].slice(0, 8));
    return true;
  };

  const submit = async () => {
    const lines = splitLines(text);
    if (!lines.length) return;
    // all understood without help?
    const ok = lines.every((ln) => !("error" in parseCommand(ln, { playhead, end: timelineDuration(timeline) })));
    if (ok) { if (runLines(lines, "")) setText(""); return; }
    setBusy(true);
    try {
      const r = await call<{ lines: string[] }>("POST", `/api/projects/${projectId}/command/ai`, { text, playhead });
      if (!r.lines.length) { setLog((l) => [{ ok: false, text: `The local AI couldn't turn "${text}" into something I can do.` }, ...l].slice(0, 8)); return; }
      if (runLines(r.lines, "AI: ")) setText("");
    } catch (e: any) {
      const bad = lines.find((ln) => "error" in parseCommand(ln, { playhead, end: timelineDuration(timeline) }))!;
      const why = (parseCommand(bad, { playhead, end: timelineDuration(timeline) }) as { error: string }).error;
      setLog((l) => [{ ok: false, text: `${why} ${e.status === 409 ? "Try one of the examples (or turn on the free local AI to type it your way)." : e.message}` }, ...l].slice(0, 8));
      setHelp(true);
    } finally { setBusy(false); }
  };

  return (
    <div className="insp-section" style={{ marginBottom: 0, display: "grid", gap: 6 }} data-testid="command-box">
      <div className="row"><h3 style={{ margin: 0 }}>Tell RJClip what to do</h3><span className="spacer" />
        <button className="btn xs ghost" aria-expanded={help} onClick={() => setHelp(!help)}>{help ? "Hide examples" : "Examples"}</button></div>
      <div className="row" style={{ gap: 6 }}>
        <input ref={input} id="rj-command" type="text" aria-label="Command" placeholder="e.g. add a zoom at 1:05" value={text} maxLength={500}
          style={{ flex: 1, minWidth: 0 }} disabled={busy}
          onChange={(e) => setText(e.target.value)} onKeyDown={(e) => { e.stopPropagation(); if (e.key === "Enter") submit(); if (e.key === "Escape") (e.target as HTMLInputElement).blur(); }} />
        <button className="btn sm primary" disabled={busy || !text.trim()} onClick={submit}>{busy ? "Thinking…" : "Do it"}</button>
      </div>
      {help && <div className="dim" style={{ fontSize: 11, display: "flex", flexWrap: "wrap", gap: 4 }} data-testid="command-examples">
        {EXAMPLES.map((x) => <button key={x} className="btn xs ghost" style={{ fontSize: 11 }} onClick={() => { setText(x); input.current?.focus(); }}>{x}</button>)}
        <span style={{ width: "100%" }}>Times like 1:05, 65s or "here". Several at once: separate with ";" or "then". Anything else goes to the free local AI (Ollama) if it's running.</span>
      </div>}
      {log.length > 0 && <div style={{ display: "grid", gap: 2, fontSize: 11 }} data-testid="command-log">
        {log.map((x, i) => <div key={i} className={x.ok ? "" : "err"} style={{ color: x.ok ? undefined : "var(--err, #e5484d)", overflowWrap: "anywhere" }}>{x.ok ? "✓ " : "✗ "}{x.text}</div>)}
      </div>}
    </div>
  );
}
