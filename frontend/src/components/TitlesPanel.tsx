import React from "react";
import { fmtTime } from "../api";
import { addTitle, removeTitle, TITLE_TEMPLATES, updateTitle, type OpResult } from "../timeline/ops";
import { FREE_TEMPLATES, type Timeline, type Title, type TitleAnim, type TitleTemplate } from "../timeline/types";

const ANIMS: [TitleAnim, string][] = [["pop", "Pop"], ["bounce", "Bounce"], ["slide_up", "Slide up"], ["typewriter", "Typewriter"], ["none", "None"]];
import { Icon } from "./ui";

/** Editor → Text: titles on the timeline (lower thirds, big titles, banners, subscribe, chapter cards). */
export default function TitlesPanel({ timeline, playhead, seek, commit, sel, setSel, top }: {
  /** shown first (Phase 15: apply the brand kit) */
  top?: React.ReactNode;
  timeline: Timeline; playhead: number; seek: (t: number) => void;
  commit: (r: OpResult, label: string, coalesce?: boolean) => boolean;
  sel: string | null; setSel: (id: string | null) => void;
}) {
  const titles = [...(timeline.titles ?? [])].sort((a, b) => a.start - b.start);
  const cur = titles.find((t) => t.id === sel) ?? null;
  const set = (patch: Partial<Title>, label: string) => cur && commit(updateTitle(timeline, cur.id, patch), label, true);

  return (
    <div className="pane-body" style={{ display: "grid", gap: 12, alignContent: "start", gridTemplateColumns: "minmax(0, 1fr)" }} data-testid="titles-panel">
      {top}
      <div className="insp-section" style={{ marginBottom: 0 }}>
        <h3 style={{ margin: 0 }}>Add a title or shape at the playhead</h3>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 4 }}>
          {TITLE_TEMPLATES.map(([tpl, label]) => (
            <button key={tpl} className="btn sm" onClick={() => {
              const r = addTitle(timeline, tpl as TitleTemplate, playhead);
              if (commit(r, `Add ${label.toLowerCase()}`) && r.id) setSel(r.id);
            }}><Icon name="plus" size={13} />{label}</button>
          ))}
        </div>
      </div>
      {titles.length > 0 && (
        <div style={{ display: "grid", gap: 4 }}>
          {titles.map((t) => (
            <div key={t.id} className={"row title-row" + (t.id === sel ? " on" : "")} style={{ fontSize: 12, gap: 6, cursor: "pointer" }}
              onClick={() => { setSel(t.id); seek(t.start + Math.min(1, t.duration / 2)); }}>
              <span className="mono">{fmtTime(t.start)}</span>
              <span className="dim">{TITLE_TEMPLATES.find((x) => x[0] === t.template)?.[1]}</span>
              <span className="ellipsis grow">{t.text}</span>
              <button className="btn xs ghost" aria-label="Delete title" onClick={(e) => { e.stopPropagation(); commit(removeTitle(timeline, t.id), "Delete title"); if (sel === t.id) setSel(null); }}><Icon name="trash" size={12} /></button>
            </div>
          ))}
        </div>
      )}
      {cur && (
        <div className="insp-section">
          <h3 style={{ margin: 0 }}>Edit title</h3>
          <label className="field">{["arrow", "circle", "box"].includes(cur.template) ? "Label (optional)" : "Text"}<input type="text" value={cur.text} maxLength={80} aria-label="Title text" onChange={(e) => set({ text: e.target.value }, "Title text")} /></label>
          {!FREE_TEMPLATES.includes(cur.template) && <label className="field">{cur.template === "chapter" ? "Above (e.g. Part 2)" : "Second line"}
            <input type="text" value={cur.subtext} maxLength={100} aria-label="Title second line" onChange={(e) => set({ subtext: e.target.value }, "Title text")} /></label>}
          <div className="insp-grid">
            <label className="field">Starts at <span className="dim">{fmtTime(cur.start)}</span>
              <button className="btn xs" onClick={() => set({ start: playhead }, "Move title")}>Move to playhead</button></label>
            <label className="field">Length (s)<input type="number" min={0.5} max={600} step={0.5} value={cur.duration} aria-label="Title length"
              onChange={(e) => Number.isFinite(+e.target.value) && set({ duration: +e.target.value }, "Title length")} /></label>
            <label className="field">Text colour<input type="color" value={cur.color} onChange={(e) => set({ color: e.target.value }, "Title colour")} /></label>
            <label className="field">Accent<input type="color" value={cur.accent} onChange={(e) => set({ accent: e.target.value }, "Title accent")} /></label>
          </div>
          {FREE_TEMPLATES.includes(cur.template) && (<>
            <div className="insp-grid">
              <label className="field">Across <span className="dim">{Math.round((cur.x ?? 0.5) * 100)}%</span>
                <input type="range" aria-label="Title across" min={0} max={1} step={0.01} value={cur.x ?? 0.5} onChange={(e) => set({ x: +e.target.value }, "Title position")} /></label>
              <label className="field">Down <span className="dim">{Math.round((cur.y ?? 0.5) * 100)}%</span>
                <input type="range" aria-label="Title down" min={0} max={1} step={0.01} value={cur.y ?? 0.5} onChange={(e) => set({ y: +e.target.value }, "Title position")} /></label>
              <label className="field">Turn <span className="dim">{Math.round(cur.rotation ?? 0)}°</span>
                <input type="range" aria-label="Title turn" min={-180} max={180} step={1} value={cur.rotation ?? 0} onChange={(e) => set({ rotation: +e.target.value }, "Title turn")} /></label>
              <label className="field">Animation
                <select aria-label="Title animation" value={cur.anim ?? "pop"} onChange={(e) => set({ anim: e.target.value as TitleAnim }, "Title animation")}>
                  {ANIMS.filter(([a]) => a !== "typewriter" || cur.template === "pop_text").map(([a, l]) => <option key={a} value={a}>{l}</option>)}
                </select></label>
            </div>
            <div className="dim" style={{ fontSize: 11 }}>Tip: drag it on the preview to place it.</div>
          </>)}
          {cur.template !== "chapter" && cur.template !== "big_title" && !FREE_TEMPLATES.includes(cur.template) && (
            <div className="row" style={{ gap: 4 }}>
              {(["left", "center", "right"] as const).map((a) => (
                <button key={a} className={"btn xs" + (cur.align === a ? " on" : " ghost")} onClick={() => set({ align: a }, "Title position")}>{a[0].toUpperCase() + a.slice(1)}</button>
              ))}
            </div>
          )}
          <label className="field">Size <span className="dim">{Math.round(cur.size * 100)}%</span>
            <input type="range" min={0.5} max={2} step={0.05} value={cur.size} onChange={(e) => set({ size: +e.target.value }, "Title size")} /></label>
        </div>
      )}
      <div className="muted" style={{ fontSize: 11 }}>Titles stay at their time on the timeline. Cutting with the Script tab moves them along.</div>
    </div>
  );
}
