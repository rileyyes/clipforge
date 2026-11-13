import React, { useEffect, useState } from "react";
import { fmtTime } from "../api";
import { fontsApi } from "../fonts";
import { applyStyle, styleOf, TEXT_PRESETS } from "../timeline/phase18";
import { realTimeDuration } from "../timeline/phase19";
import { parseTime } from "../timeline/effects";
import FontSelect from "./FontSelect";
import { addTitle, removeTitle, RETIRED_TEMPLATES, TITLE_TEMPLATES, updateTitle, type OpResult } from "../timeline/ops";
import { FREE_TEMPLATES, type TextStyle, type Timeline, type Title, type TitleAnim, type TitleTemplate } from "../timeline/types";

const STICKERS = ["😂", "🤣", "💀", "☠️", "🔥", "😱", "😭", "👀", "🤯", "😡", "🤔", "😎", "👍", "👎", "💯", "❤️",
  "💥", "⚡", "🎯", "🏆", "🍿", "🔪", "🩸", "👻", "🧟", "🎃", "🤡", "🐐", "🧠", "😈", "🙏", "❓"];
const ANIMS: [TitleAnim, string][] = [["pop", "Pop"], ["words", "Word by word"], ["bounce", "Bounce"], ["slide_up", "Slide up"], ["typewriter", "Typewriter"], ["none", "None"]];

/** Ticker values as you'd type them: 1:30 for time, 1,250 for money/numbers. */
function fmtCount(v: number, f: Title["format"]): string {
  if ((f ?? "time") === "time") { const s = Math.round(v); const a = Math.abs(s); return `${s < 0 ? "-" : ""}${Math.floor(a / 60)}:${String(a % 60).padStart(2, "0")}`; }
  return String(Math.round(v));
}
function readCount(text: string, f: Title["format"]): number | null {
  const t = text.trim().replace(/[$,\s]/g, "");
  if ((f ?? "time") === "time" && t.includes(":")) {
    const neg = t.startsWith("-"); const v = parseTime(t.replace(/^-/, ""));
    return v === null ? null : neg ? -v : v;
  }
  const n = Number(t);
  return Number.isFinite(n) && t !== "" ? n : null;
}
import { Icon } from "./ui";

/** Editor → Text: titles on the timeline (lower thirds, big titles, banners, subscribe, chapter cards). */
export default function TitlesPanel({ timeline, playhead, seek, commit, sel, setSel, top, bottom, drawingFor = null, onDraw }: {
  /** Phase 19: draw a highlighter box / route points on the preview for this title (kind null = stop) */
  drawingFor?: string | null; onDraw?: (id: string, kind: "box" | "points" | null) => void;
  /** shown first (Phase 15: apply the brand kit) */
  top?: React.ReactNode;
  /** shown last (name tags) */
  bottom?: React.ReactNode;
  timeline: Timeline; playhead: number; seek: (t: number) => void;
  commit: (r: OpResult, label: string, coalesce?: boolean) => boolean;
  sel: string | null; setSel: (id: string | null) => void;
}) {
  const titles = [...(timeline.titles ?? [])].sort((a, b) => a.start - b.start);
  const cur = titles.find((t) => t.id === sel) ?? null;
  const set = (patch: Partial<Title>, label: string) => cur && commit(updateTitle(timeline, cur.id, patch), label, true);
  const [mine, setMine] = useState<TextStyle[]>([]);
  useEffect(() => { fontsApi.styles().then(setMine).catch(() => {}); }, []);
  const shape = cur ? ["arrow", "circle", "box"].includes(cur.template) && !cur.text : false;

  return (
    <div className="pane-body" style={{ display: "grid", gap: 12, alignContent: "start", gridTemplateColumns: "minmax(0, 1fr)" }} data-testid="titles-panel">
      {top}
      <div className="insp-section" style={{ marginBottom: 0 }}>
        <h3 style={{ margin: 0 }}>Add a title or shape at the playhead</h3>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 4 }}>
          {TITLE_TEMPLATES.filter(([tpl]) => !RETIRED_TEMPLATES.includes(tpl)).map(([tpl, label]) => (
            <button key={tpl + label} className="btn sm" onClick={() => {
              const r = addTitle(timeline, tpl as TitleTemplate, playhead, label);
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
          {cur.template === "sticker" ? (
            <div className="field">Emoji
              <div style={{ display: "grid", gridTemplateColumns: "repeat(8, 1fr)", gap: 2 }} data-testid="sticker-picker">
                {STICKERS.map((em) => <button key={em} className={"btn xs" + (cur.text === em ? " on" : " ghost")} aria-label={`Sticker ${em}`}
                  style={{ fontFamily: "'rjf-emoji'", fontSize: 16, padding: 2 }} onClick={() => set({ text: em }, "Sticker")}>{em}</button>)}
              </div>
            </div>
          ) : <label className="field">{["arrow", "circle", "box"].includes(cur.template) ? "Label (optional)" : cur.template === "count_card" ? "Name" : cur.template === "tally" ? "Heading" : "Text"}<input type="text" value={cur.text} maxLength={80} aria-label="Title text" onChange={(e) => set({ text: e.target.value }, "Title text")} /></label>}
          {cur.template === "number_card" && <label className="field">Number<input type="number" min={0} max={999} value={cur.number ?? 1} aria-label="Card number"
            onChange={(e) => Number.isFinite(+e.target.value) && set({ number: +e.target.value }, "Card number")} /></label>}
          {cur.template === "ticker" && (<>
            <div className="insp-grid">
              <label className="field">Shows<select aria-label="Ticker kind" value={cur.format ?? "time"} onChange={(e) => set({ format: e.target.value as Title["format"] }, "Ticker kind")}>
                <option value="time">Time (1:05)</option><option value="money">Money ($1,250)</option><option value="number">Number (1,250)</option></select></label>
              <span />
              <label className="field">From<input type="text" aria-label="Count from" defaultValue={fmtCount(cur.count_from ?? 60, cur.format)} key={`f${cur.id}${cur.count_from}${cur.format}`}
                onBlur={(e) => { const v = readCount(e.target.value, cur.format); if (v !== null) set({ count_from: v }, "Ticker from"); }}
                onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }} /></label>
              <label className="field">To<input type="text" aria-label="Count to" defaultValue={fmtCount(cur.count_to ?? 0, cur.format)} key={`t${cur.id}${cur.count_to}${cur.format}`}
                onBlur={(e) => { const v = readCount(e.target.value, cur.format); if (v !== null) set({ count_to: v }, "Ticker to"); }}
                onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }} /></label>
            </div>
            {(cur.format ?? "time") === "time" && <div className="row" style={{ gap: 6, fontSize: 11 }}>
              <span className="dim">{Math.abs(realTimeDuration(cur) - cur.duration) < 0.05 ? "Runs in real time" : `Runs ${((Math.abs((cur.count_to ?? 0) - (cur.count_from ?? 60))) / Math.max(0.05, cur.duration - 0.3)).toFixed(1)}× real time`}</span>
              <button className="btn xs" onClick={() => set({ duration: realTimeDuration(cur) }, "Timer in real time")}>Real time</button></div>}
            <div className="dim" style={{ fontSize: 11 }}>The text above it is the label (e.g. TIME LEFT, PRIZE); leave it empty for none. A timer going down turns the accent colour in its last 10 seconds.</div>
          </>)}
          {cur.template === "route" && (
            <div className="row" style={{ gap: 4, flexWrap: "wrap" }}>
              {drawingFor === cur.id
                ? <button className="btn sm primary" onClick={() => onDraw?.(cur.id, null)}>Cancel drawing</button>
                : <button className="btn sm" onClick={() => onDraw?.(cur.id, "points")}>Click the route on the preview</button>}
              <span className="dim" style={{ fontSize: 11 }}>{(cur.points ?? []).length} points. Put a map screenshot (or any picture) on the timeline under it; the line draws itself, then a pin with the text appears at the end.</span>
            </div>
          )}
          {cur.template === "highlight" && (<>
            <div className="row" style={{ gap: 4, flexWrap: "wrap" }}>
              {drawingFor === cur.id
                ? <button className="btn sm primary" onClick={() => onDraw?.(cur.id, null)}>Cancel drawing</button>
                : <button className="btn sm" onClick={() => onDraw?.(cur.id, "box")}>Draw the box on the preview</button>}
            </div>
            <div className="insp-grid">
              <label className="field">Width <span className="dim">{Math.round((cur.w ?? 0.4) * 100)}%</span>
                <input type="range" aria-label="Highlight width" min={0.02} max={1} step={0.01} value={cur.w ?? 0.4} onChange={(e) => set({ w: +e.target.value }, "Highlight size")} /></label>
              <label className="field">Height <span className="dim">{Math.round((cur.h ?? 0.08) * 100)}%</span>
                <input type="range" aria-label="Highlight height" min={0.02} max={0.5} step={0.005} value={cur.h ?? 0.08} onChange={(e) => set({ h: +e.target.value }, "Highlight size")} /></label>
            </div>
            <div className="dim" style={{ fontSize: 11 }}>A highlighter pen sweeps across the box — for a quote in a screenshot of an article or a post. The colour is the Accent.</div>
          </>)}
          {cur.template === "tally" && <div className="dim" style={{ fontSize: 11 }}>Lists every callout card before it.</div>}
          {!FREE_TEMPLATES.includes(cur.template) && cur.template !== "tally" && <label className="field">{cur.template === "chapter" ? "Above (e.g. Part 2)" : cur.template === "count_card" ? "Detail" : "Second line"}
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
                  {ANIMS.filter(([a]) => (a !== "typewriter" && a !== "words") || cur.template === "pop_text").map(([a, l]) => <option key={a} value={a}>{l}</option>)}
                </select></label>
            </div>
            <div className="dim" style={{ fontSize: 11 }}>Tip: drag it on the preview to place it.</div>
          </>)}
          {["lower_third", "top_banner", "subscribe"].includes(cur.template) && (
            <div className="row" style={{ gap: 4 }}>
              {(["left", "center", "right"] as const).map((a) => (
                <button key={a} className={"btn xs" + (cur.align === a ? " on" : " ghost")} onClick={() => set({ align: a }, "Title position")}>{a[0].toUpperCase() + a.slice(1)}</button>
              ))}
            </div>
          )}
          <label className="field">Size <span className="dim">{Math.round(cur.size * 100)}%</span>
            <input type="range" min={0.5} max={2} step={0.05} value={cur.size} onChange={(e) => set({ size: +e.target.value }, "Title size")} /></label>
          {!shape && cur.template !== "sticker" && cur.template !== "highlight" && (
            <div className="insp-section" style={{ margin: 0 }} data-testid="text-style">
              <h3 style={{ margin: 0 }}>Font & style</h3>
              <div className="row" style={{ flexWrap: "wrap", gap: 4 }}>
                {[...TEXT_PRESETS, ...mine].map((p, i) => (
                  <span key={p.name + i} className="row" style={{ gap: 0 }}>
                    <button className="btn xs" title={`Use the ${p.name} style`}
                      style={{ fontFamily: `'rjf-${p.font}', 'DejaVu Sans'`, color: p.color, textShadow: p.glow ? `0 0 6px ${p.glow_color}` : undefined,
                        WebkitTextStroke: p.stroke ? `1px ${p.stroke_color}` : undefined, background: "#222", fontWeight: p.font ? 400 : 700 }}
                      onClick={() => set(applyStyle(p), "Text style")}>{i >= TEXT_PRESETS.length ? "★ " : ""}{p.name}</button>
                    {i >= TEXT_PRESETS.length && <button className="btn xs ghost" aria-label={`Delete my style ${p.name}`} title="Delete this style of yours"
                      onClick={async () => { try { setMine(await fontsApi.saveStyles(mine.filter((m) => m.name !== p.name))); } catch (e: any) { alert(e.message); } }}>×</button>}
                  </span>
                ))}
              </div>
              <FontSelect value={cur.font} onChange={(font) => set({ font }, "Title font")} />
              <div className="insp-grid">
                <label className="field">Outline <span className="dim">{cur.stroke == null ? "default" : `${cur.stroke}px`}</span>
                  <input type="range" aria-label="Outline" min={0} max={24} step={1} value={cur.stroke ?? 0} onChange={(e) => set({ stroke: +e.target.value }, "Title outline")} /></label>
                <label className="field">Outline colour<input type="color" aria-label="Outline colour" value={cur.stroke_color ?? "#000000"} onChange={(e) => set({ stroke_color: e.target.value, stroke: cur.stroke ?? 6 }, "Title outline")} /></label>
                <label className="field">Shadow <span className="dim">{cur.shadow == null ? "default" : `${cur.shadow}px`}</span>
                  <input type="range" aria-label="Shadow" min={0} max={24} step={1} value={cur.shadow ?? 0} onChange={(e) => set({ shadow: +e.target.value }, "Title shadow")} /></label>
                <label className="field">Glow <span className="dim">{cur.glow ? `${cur.glow}px` : "off"}</span>
                  <input type="range" aria-label="Glow" min={0} max={40} step={1} value={cur.glow ?? 0} onChange={(e) => set({ glow: +e.target.value }, "Title glow")} /></label>
                <label className="field">Glow colour<input type="color" aria-label="Glow colour" value={cur.glow_color ?? "#ffde00"} onChange={(e) => set({ glow_color: e.target.value, glow: cur.glow || 12 }, "Title glow")} /></label>
              </div>
              <div className="row" style={{ gap: 4 }}>
                <button className="btn xs" onClick={() => set({ font: null, stroke: null, shadow: null, glow: 0 }, "Reset text style")}>Reset style</button>
                <button className="btn xs" onClick={async () => {
                  const name = prompt("Name this style", `My style ${mine.length + 1}`)?.trim().slice(0, 30);
                  if (!name) return;
                  try { setMine(await fontsApi.saveStyles([...mine.filter((m) => m.name !== name), styleOf(cur, name)].slice(-40))); }
                  catch (e: any) { alert(e.message); }
                }}>Save as my style</button>
              </div>
            </div>
          )}
        </div>
      )}
      {bottom}
      <div className="muted" style={{ fontSize: 11 }}>Titles stay at their time on the timeline. Cutting with the Script tab moves them along.</div>
    </div>
  );
}
