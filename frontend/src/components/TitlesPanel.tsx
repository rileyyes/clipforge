import React, { useState } from "react";
import { fmtTime } from "../api";
import { addTitle, removeTitle, TITLE_TEMPLATES, updateTitle, type OpResult } from "../timeline/ops";
import type { Timeline, Title, TitleTemplate } from "../timeline/types";
import { Icon } from "./ui";

/** Editor → Text: titles on the timeline (lower thirds, big titles, banners, subscribe, chapter cards). */
export default function TitlesPanel({ timeline, playhead, seek, commit }: {
  timeline: Timeline; playhead: number; seek: (t: number) => void;
  commit: (r: OpResult, label: string, coalesce?: boolean) => boolean;
}) {
  const titles = [...(timeline.titles ?? [])].sort((a, b) => a.start - b.start);
  const [sel, setSel] = useState<string | null>(null);
  const cur = titles.find((t) => t.id === sel) ?? null;
  const set = (patch: Partial<Title>, label: string) => cur && commit(updateTitle(timeline, cur.id, patch), label, true);

  return (
    <div className="pane-body" style={{ display: "grid", gap: 12, alignContent: "start" }} data-testid="titles-panel">
      <div className="insp-section" style={{ marginBottom: 0 }}>
        <h3 style={{ margin: 0 }}>Add a title at the playhead</h3>
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
          <label className="field">Text<input type="text" value={cur.text} maxLength={80} aria-label="Title text" onChange={(e) => set({ text: e.target.value }, "Title text")} /></label>
          <label className="field">{cur.template === "chapter" ? "Above (e.g. Part 2)" : "Second line"}
            <input type="text" value={cur.subtext} maxLength={100} aria-label="Title second line" onChange={(e) => set({ subtext: e.target.value }, "Title text")} /></label>
          <div className="insp-grid">
            <label className="field">Starts at <span className="dim">{fmtTime(cur.start)}</span>
              <button className="btn xs" onClick={() => set({ start: playhead }, "Move title")}>Move to playhead</button></label>
            <label className="field">Length (s)<input type="number" min={0.5} max={600} step={0.5} value={cur.duration} aria-label="Title length"
              onChange={(e) => Number.isFinite(+e.target.value) && set({ duration: +e.target.value }, "Title length")} /></label>
            <label className="field">Text colour<input type="color" value={cur.color} onChange={(e) => set({ color: e.target.value }, "Title colour")} /></label>
            <label className="field">Accent<input type="color" value={cur.accent} onChange={(e) => set({ accent: e.target.value }, "Title accent")} /></label>
          </div>
          {cur.template !== "chapter" && cur.template !== "big_title" && (
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
