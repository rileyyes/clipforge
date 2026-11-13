import React, { useState } from "react";
import { fmtTime } from "../api";
import { addTitle, setTrackTag, type OpResult } from "../timeline/ops";
import { addCounter, addCount, countAt, counterTicks, countCards, MAX_COUNTERS, removeCounter, updateCounter } from "../timeline/phase18";
import type { Counter, Effect, NameTags, Sound, Timeline } from "../timeline/types";
import FontSelect from "./FontSelect";
import { Icon, useToast } from "./ui";

const SOUNDS: (Sound | "")[] = ["boom", "ding", "pop", "scratch", "whoosh", "airhorn", ""];
const CORNERS: [string, number, number][] = [["Top right", 0.86, 0.12], ["Top left", 0.14, 0.12], ["Bottom right", 0.86, 0.82], ["Bottom left", 0.14, 0.82]];

/** Editor → Text: counter tools (a counter, one-click counts with callout cards, a tally screen). */
export function CounterPanel({ timeline, effects, playhead, seek, commit, commitBoth, setSel }: {
  timeline: Timeline; effects: Effect[]; playhead: number; seek: (t: number) => void;
  commit: (r: OpResult, label: string, coalesce?: boolean) => boolean;
  /** one undo step for a change to the timeline and the effects together */
  commitBoth: (tl: Timeline, fx: Effect[], label: string) => void;
  setSel: (id: string | null) => void;
}) {
  const toast = useToast();
  const [name, setName] = useState("");
  const [how, setHow] = useState("");
  const [sound, setSound] = useState<Sound | "">("boom");
  const counters = timeline.counters ?? [];
  const cards = countCards(timeline);
  const set = (c: Counter, patch: Partial<Counter>, label: string) => commit(updateCounter(timeline, c.id, patch), label, true);

  const countIt = () => {
    const r = addCount(timeline, effects, playhead, name.trim(), how.trim(), sound || null);
    if ("error" in r) return toast(r.error, true);
    commitBoth(r.timeline, r.effects, "Count it");
    setSel(r.titleId);
    setName(""); setHow("");
    toast(`#${countCards(r.timeline).length} counted at ${fmtTime(playhead)}`);
  };

  return (
    <div className="insp-section" data-testid="counter-tools">
      <h3 style={{ margin: 0 }}>Counter</h3>
      <div className="dim" style={{ fontSize: 11 }}>Count things as they happen — eliminations, goals, fails, jump scares, anything. Pause on the moment and press Count it: the counter goes up and a callout card shows the name and detail. Both stay on that moment when you cut or move clips.</div>
      <div className="insp-grid">
        <label className="field">Name<input type="text" value={name} maxLength={80} placeholder="e.g. Steve" aria-label="Callout name" onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") countIt(); }} /></label>
        <label className="field">Detail<input type="text" value={how} maxLength={100} placeholder="e.g. fell in the trap" aria-label="Callout detail" onChange={(e) => setHow(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") countIt(); }} /></label>
        <label className="field">Sound<select value={sound} aria-label="Count sound" onChange={(e) => setSound(e.target.value as Sound | "")}>
          {SOUNDS.map((x) => <option key={x} value={x}>{x || "None"}</option>)}</select></label>
      </div>
      <div className="row" style={{ gap: 4, flexWrap: "wrap" }}>
        <button className="btn sm primary" onClick={countIt}><Icon name="plus" size={13} />Count it at {fmtTime(playhead)}</button>
        {counters[0] && <button className="btn sm" title="Count without a callout card" onClick={() => {
          const e = countAt(timeline, counters[0].id, playhead, sound || null);
          if ("error" in e) return toast(e.error!, true);
          commitBoth(timeline, [...effects, e], "Count +1");
        }}>+1 only</button>}
        <button className="btn sm" title="The counter stops here too, so the tally has the screen" onClick={() => {
          const r = addTitle(timeline, "tally", playhead);
          if (r.error !== undefined || !r.id) return toast(r.error ?? "Couldn't add the tally", true);
          let tl = r.timeline;
          for (const c of tl.counters ?? []) {
            if (c.end !== null || playhead <= c.start + 0.1) continue;
            const u = updateCounter(tl, c.id, { end: playhead });
            if (u.error === undefined) tl = u.timeline;
          }
          if (commit({ timeline: tl }, "Add end tally")) setSel(r.id);
        }}>Tally screen here</button>
      </div>
      {cards.length > 0 && <div className="dim" style={{ fontSize: 11, display: "flex", flexWrap: "wrap", gap: 2, alignItems: "center" }}>{cards.length} callout card{cards.length === 1 ? "" : "s"}: {cards.slice(-5).map((c) => (
        <button key={c.id} className="btn xs ghost" onClick={() => { setSel(c.id); seek(c.start + 0.5); }}>#{c.n} {c.text}</button>))}</div>}

      {counters.map((c) => {
        const ticks = counterTicks(timeline, effects, c.id);
        return (
          <div key={c.id} className="insp-section" style={{ margin: 0 }} data-testid="counter-settings">
            <div className="row" style={{ gap: 6 }}>
              <input type="text" value={c.label} maxLength={24} aria-label="Counter label" style={{ flex: 1, minWidth: 0 }} onChange={(e) => set(c, { label: e.target.value }, "Counter label")} />
              <span className="dim" style={{ fontSize: 11 }}>{ticks.length} counted</span>
              <button className="btn xs ghost" aria-label="Delete counter" onClick={() => {
                const n = effects.filter((e) => e.kind === "count" && e.counter === c.id).length;
                if (n && !confirm(`Delete this counter and its ${n} count${n === 1 ? "" : "s"}? (Callout cards stay.)`)) return;
                const r = removeCounter(timeline, effects, c.id);
                commitBoth(r.timeline, r.effects, "Delete counter");
              }}><Icon name="trash" size={12} /></button>
            </div>
            <div className="insp-grid">
              <label className="field">Starts at<input type="number" min={0} max={9999} value={c.start_value} aria-label="Counter starts at"
                onChange={(e) => Number.isFinite(+e.target.value) && set(c, { start_value: +e.target.value }, "Counter start")} /></label>
              <label className="field">Place<select aria-label="Counter place" value={CORNERS.find(([, x, y]) => Math.abs(x - c.x) < 0.01 && Math.abs(y - c.y) < 0.01)?.[0] ?? ""}
                onChange={(e) => { const k = CORNERS.find(([n]) => n === e.target.value); if (k) set(c, { x: k[1], y: k[2] }, "Counter place"); }}>
                <option value="">Custom</option>{CORNERS.map(([n]) => <option key={n}>{n}</option>)}</select></label>
              <label className="field">Text colour<input type="color" value={c.color} onChange={(e) => set(c, { color: e.target.value }, "Counter colour")} /></label>
              <label className="field">Accent<input type="color" value={c.accent} onChange={(e) => set(c, { accent: e.target.value }, "Counter colour")} /></label>
              <label className="field">Size <span className="dim">{Math.round(c.size * 100)}%</span>
                <input type="range" min={0.5} max={2} step={0.05} value={c.size} onChange={(e) => set(c, { size: +e.target.value }, "Counter size")} /></label>
              <FontSelect value={c.font} onChange={(font) => set(c, { font }, "Counter font")} />
            </div>
            <div className="row" style={{ gap: 4, fontSize: 11, flexWrap: "wrap" }}>
              <span className="muted">Shown from {fmtTime(c.start)}{c.end != null ? ` to ${fmtTime(c.end)}` : " to the end"}</span>
              <button className="btn xs" onClick={() => { const r = updateCounter(timeline, c.id, { start: playhead, end: c.end != null && c.end <= playhead + 0.1 ? null : c.end }); commit(r, "Counter shown from"); }}>From playhead</button>
              <button className="btn xs" onClick={() => commit(updateCounter(timeline, c.id, { end: playhead }), "Counter shown until")}>Until playhead</button>
              {c.end != null && <button className="btn xs ghost" onClick={() => commit(updateCounter(timeline, c.id, { end: null }), "Counter shown until")}>To the end</button>}
            </div>
          </div>
        );
      })}
      {counters.length < MAX_COUNTERS && <button className="btn sm" onClick={() => commit(addCounter(timeline, counters.length ? "SCORE" : "COUNT"), "Add counter")}>
        <Icon name="plus" size={13} />{counters.length ? "Another counter" : "Add a counter"}</button>}
    </div>
  );
}

/** Editor → Text: name tags for the people talking (voice-chat style). */
export function NameTagsPanel({ timeline, commit }: { timeline: Timeline; commit: (r: OpResult, label: string, coalesce?: boolean) => boolean }) {
  const nt: NameTags = timeline.name_tags ?? { enabled: false, corner: "tl", size: 1, only_talking: false };
  const set = (p: Partial<NameTags>, label: string) => commit({ timeline: { ...timeline, name_tags: { ...nt, ...p } } }, label, true);
  const audio = timeline.tracks.filter((t) => t.kind === "audio" && t.role !== "music");
  return (
    <div className="insp-section" data-testid="name-tags">
      <h3 style={{ margin: 0 }}>Name tags</h3>
      <div className="dim" style={{ fontSize: 11 }}>Put each person's mic on its own audio track and give it a name: their tag lights up while their track is loud. It goes by loudness, so game sound on a mic counts as talking.</div>
      <label className="row" style={{ fontSize: 12 }}><input type="checkbox" checked={nt.enabled} aria-label="Show name tags" onChange={(e) => set({ enabled: e.target.checked }, "Name tags")} />Show name tags</label>
      {audio.map((t) => (
        <div key={t.id} className="row" style={{ gap: 6 }}>
          <span className="mono dim" style={{ width: 28 }}>{t.name}</span>
          <input type="text" value={t.tag ?? ""} maxLength={24} placeholder="Name" aria-label={`Name tag for ${t.name}`} style={{ flex: 1, minWidth: 0 }}
            onChange={(e) => commit(setTrackTag(timeline, t.id, e.target.value), "Name tag", true)} />
          <input type="color" style={{ flex: "none", width: 36 }} value={t.tag_color ?? "#5865f2"} aria-label={`Tag colour for ${t.name}`} onChange={(e) => commit(setTrackTag(timeline, t.id, t.tag ?? "", e.target.value), "Name tag colour", true)} />
        </div>
      ))}
      <div className="insp-grid">
        <label className="field">Corner<select value={nt.corner} aria-label="Name tag corner" onChange={(e) => set({ corner: e.target.value as NameTags["corner"] }, "Name tag corner")}>
          <option value="tl">Top left</option><option value="tr">Top right</option><option value="bl">Bottom left</option><option value="br">Bottom right</option></select></label>
        <label className="field">Size <span className="dim">{Math.round(nt.size * 100)}%</span>
          <input type="range" min={0.5} max={2} step={0.05} value={nt.size} onChange={(e) => set({ size: +e.target.value }, "Name tag size")} /></label>
      </div>
      <label className="row" style={{ fontSize: 12 }}><input type="checkbox" checked={nt.only_talking} onChange={(e) => set({ only_talking: e.target.checked }, "Name tags")} />Only show whoever is talking</label>
    </div>
  );
}
