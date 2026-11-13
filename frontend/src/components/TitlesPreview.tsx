import React from "react";
import { fontCss } from "../fonts";
import { FREE_TEMPLATES, type Title } from "../timeline/types";

/** CSS versions of the title templates for the monitor (export: backend/app/titles.py, libass).
 *  Same sizes (relative to the output height), positions and in/out timing. */
const IN = 0.4, OUT = 0.3;
const ease = (x: number) => 1 - Math.pow(1 - Math.min(1, Math.max(0, x)), 3);

/** Phase 18 font and text style on top of a template's own look (export: titles.py _restyle). */
export function styleCss(x: Title, s: number, k: number): React.CSSProperties {
  const out: React.CSSProperties = {};
  if (x.font) { out.fontFamily = fontCss(x.font); out.fontWeight = 400; }
  const shadows: string[] = [];
  if (x.stroke != null) { out.WebkitTextStroke = `${x.stroke * s * 2}px ${x.stroke_color ?? "#000000"}`; out.paintOrder = "stroke fill"; }
  if ((x.glow ?? 0) > 0) shadows.push(`0 0 ${(x.glow ?? 0) * s}px ${x.glow_color}`, `0 0 ${(x.glow ?? 0) * s * 0.5}px ${x.glow_color}`);
  if (x.shadow != null) shadows.push(x.shadow > 0 ? `${x.shadow * s}px ${x.shadow * s}px 0 rgba(0,0,0,.4)` : "0 0 0 transparent");
  if (shadows.length) out.textShadow = shadows.join(", ");
  void k;
  return out;
}

export interface TallyInfo { entries: [string, string][]; total: number }

export default function TitlesPreview({ titles, t, k, W, H, ox, oy, sel, onMove, tally }: {
  titles: Title[]; t: number; k: number; W: number; H: number; ox: number; oy: number;
  /** what an end tally lists (death cards before it, total) */
  tally?: (x: Title) => TallyInfo;
  /** the selected title; pop-up words and shapes can then be dragged into place */
  sel?: string | null; onMove?: (id: string, x: number, y: number, done: boolean) => void;
}) {
  // (a title added at the playhead is saved rounded to the µs, so allow for that)
  const on = titles.filter((x) => t >= x.start - 1e-4 && t < x.start + x.duration).sort((a, b) => a.start - b.start);
  return <>{on.map((x) => FREE_TEMPLATES.includes(x.template)
    ? <Free key={x.id} x={x} t={Math.max(0, t - x.start)} k={k} W={W} H={H} ox={ox} oy={oy} selected={sel === x.id} onMove={onMove} />
    : <One key={x.id} x={x} t={Math.max(0, t - x.start)} k={k} W={W} H={H} ox={ox} oy={oy}
        killN={x.template === "death_card" ? killNumber(titles, x) : 0} tally={x.template === "tally" ? tally?.(x) : undefined} />)}</>;
}

function killNumber(all: Title[], x: Title): number {
  return all.filter((c) => c.template === "death_card").sort((a, b) => a.start - b.start).findIndex((c) => c.id === x.id) + 1;
}

/** pop_text, arrow, circle, box (export: titles.py _free): centre at (x, y), turned clockwise, in-animation. */
function Free({ x, t, k, W, H, ox, oy, selected, onMove }: {
  x: Title; t: number; k: number; W: number; H: number; ox: number; oy: number; selected: boolean;
  onMove?: (id: string, x: number, y: number, done: boolean) => void;
}) {
  const s = (H / 1080) * x.size * k;
  const w = W * k, h = H * k;
  const cx = ox + (x.x ?? 0.5) * w, cy = oy + (x.y ?? 0.5) * h;
  const anim = x.anim ?? "pop";
  let dy = 0, sx = 1, sy = 1;
  if (anim === "pop" || (anim === "typewriter" && x.template !== "pop_text")) {
    const p = IN * 0.6;
    sx = sy = t < p ? 0.4 + 0.72 * (t / p) : t < IN ? 1.12 - 0.12 * ((t - p) / (IN - p)) : 1;
  } else if (anim === "slide_up") dy = H * 0.08 * k * (1 - Math.min(1, t / IN));
  else if (anim === "bounce") {
    if (t < 0.25) dy = -H * 0.18 * k * (1 - t / 0.25);
    else if (t < 0.33) { const f = (t - 0.25) / 0.08; sx = 1 + 0.18 * f; sy = 1 - 0.16 * f; }
    else if (t < 0.43) { const f = (t - 0.33) / 0.1; sx = 1.18 - 0.24 * f; sy = 0.84 + 0.24 * f; }
    else if (t < 0.52) { const f = (t - 0.43) / 0.09; sx = 0.94 + 0.06 * f; sy = 1.08 - 0.08 * f; }
  }
  const fade = Math.min(1, t / 0.12, Math.max(0, (x.duration - t) / OUT));
  const drag = (e: React.PointerEvent) => {
    if (!selected || !onMove) return;
    e.preventDefault(); e.stopPropagation();
    const box = (e.currentTarget.parentElement as HTMLElement).getBoundingClientRect();
    const at = (ev: PointerEvent | React.PointerEvent) => [Math.min(1, Math.max(0, (ev.clientX - box.left - ox) / w)), Math.min(1, Math.max(0, (ev.clientY - box.top - oy) / h))] as const;
    const mv = (ev: PointerEvent) => { const [a, b] = at(ev); onMove(x.id, a, b, false); };
    const up = (ev: PointerEvent) => { window.removeEventListener("pointermove", mv); const [a, b] = at(ev); onMove(x.id, a, b, true); };
    window.addEventListener("pointermove", mv);
    window.addEventListener("pointerup", up, { once: true });
  };
  const stroke = Math.max(3, 12 * s / k) * k;
  let body: React.ReactNode;
  if (x.template === "pop_text") {
    const step = Math.min(0.06, Math.min(0.8, x.duration * 0.5) / Math.max(1, x.text.length));
    const shown = anim === "typewriter" ? [...x.text].slice(0, Math.floor(t / step) + 1).join("") : x.text;
    body = <span style={{ fontSize: 96 * s, fontFamily: "'DejaVu Sans', Arial, sans-serif", fontWeight: 700, color: x.color, whiteSpace: "nowrap",
      WebkitTextStroke: `${Math.max(2, 7 * s / k) * k * 2}px #000`, paintOrder: "stroke fill", textShadow: `${3 * s}px ${3 * s}px 0 rgba(0,0,0,.5)`,
      visibility: "visible", ...styleCss(x, s, k) }}>{shown}<span style={{ visibility: "hidden" }}>{anim === "typewriter" ? x.text.slice(shown.length) : ""}</span></span>;
  } else if (x.template === "sticker") {
    // the sticker font is line art: an outline in its own colour makes the lines bold (export: titles.py)
    body = <span style={{ fontSize: 240 * s, fontFamily: fontCss("emoji"), fontWeight: 400, color: x.color, whiteSpace: "nowrap", lineHeight: 1,
      WebkitTextStroke: `${Math.max(1, 2.5 * s / k) * k * 2}px ${x.color}`, paintOrder: "stroke fill",
      textShadow: `${5 * s}px ${5 * s}px 0 rgba(0,0,0,.4)`, ...styleCss({ ...x, font: null }, s, k) }}>{x.text}</span>;
  } else if (x.template === "arrow") {
    const L = 260 * s, T = 34 * s, hw = T * 1.3, hl = T * 2.2;
    body = <svg width={L + 8} height={2 * hw + 8} style={{ overflow: "visible", display: "block" }}>
      <polygon transform="translate(4,4)" fill={x.accent} stroke="#000" strokeWidth={Math.max(1.5, 4 * s / k) * k * 2} paintOrder="stroke"
        points={`0,${hw - T / 2} ${L - hl},${hw - T / 2} ${L - hl},0 ${L},${hw} ${L - hl},${2 * hw} ${L - hl},${hw + T / 2} 0,${hw + T / 2}`} /></svg>;
  } else if (x.template === "circle") {
    const r = 120 * s;
    body = <div style={{ width: 2 * r, height: 2 * r, borderRadius: "50%", border: `${stroke}px solid ${x.accent}`, margin: -stroke }} />;
  } else {
    body = <div style={{ width: 320 * s, height: 200 * s, border: `${stroke}px solid ${x.accent}`, margin: -stroke, borderRadius: stroke / 2 }} />;
  }
  return (
    <>
      <div data-testid="title-preview" data-template={x.template} onPointerDown={drag}
        style={{ position: "absolute", left: cx, top: cy + dy, opacity: fade, zIndex: 1600,
          transform: `translate(-50%,-50%) rotate(${x.rotation ?? 0}deg) scale(${sx},${sy})`,
          pointerEvents: selected && onMove ? "auto" : "none", cursor: selected && onMove ? "move" : undefined,
          outline: selected && onMove ? "1px dashed rgba(255,255,255,.7)" : undefined, outlineOffset: 6 }}>{body}</div>
      {x.template !== "pop_text" && x.template !== "sticker" && x.text && (
        <div style={{ position: "absolute", left: cx, top: cy + 140 * s, transform: "translateX(-50%)", opacity: fade, pointerEvents: "none", zIndex: 1600,
          fontSize: 48 * s, fontFamily: "'DejaVu Sans', Arial, sans-serif", fontWeight: 700, color: x.color, whiteSpace: "nowrap",
          WebkitTextStroke: `${Math.max(2, 5 * s / k) * k * 2}px #000`, paintOrder: "stroke fill", ...styleCss(x, s, k) }}>{x.text}</div>
      )}
    </>
  );
}

function One({ x, t, k, W, H, ox, oy, killN, tally }: { x: Title; t: number; k: number; W: number; H: number; ox: number; oy: number;
  killN: number; tally?: TallyInfo }) {
  const s = (H / 1080) * x.size * k;             // px on screen per design px at 1080p
  const fadeOut = Math.min(1, Math.max(0, (x.duration - t) / OUT));
  const pin = ease(t / IN);
  const base: React.CSSProperties = { position: "absolute", pointerEvents: "none", fontFamily: "'DejaVu Sans', Arial, sans-serif", fontWeight: 700, color: x.color, whiteSpace: "nowrap",
    ...styleCss(x, s, k) };
  const frame = (style: React.CSSProperties, children: React.ReactNode) =>
    <div data-testid="title-preview" data-template={x.template} style={{ ...base, ...style, opacity: (style.opacity as number ?? 1) * fadeOut }}>{children}</div>;
  const left = ox, top = oy, w = W * k, h = H * k;
  switch (x.template) {
    case "lower_third": {
      const slide = (1 - pin) * w * 0.6;
      const [lx, tx] = x.align === "right" ? [left + w * 0.95 + slide, "-100%"] : x.align === "center" ? [left + w / 2, "-50%"] : [left + w * 0.05 - slide, "0"];
      return frame({ left: lx, top: top + h * 0.9, transform: `translate(${tx}, -100%)`, background: "rgba(0,0,0,.62)",
        borderLeft: `${10 * s}px solid ${x.accent}`, borderRadius: 10 * s, padding: `${28 * s * 0.45}px ${28 * s}px ${28 * s * 0.55}px` }, <>
        <div style={{ fontSize: 54 * s, lineHeight: 1.25 }}>{x.text}</div>
        {x.subtext && <div style={{ fontSize: 34 * s, fontWeight: 400, opacity: 0.8, lineHeight: 1.3 }}>{x.subtext}</div>}
      </>);
    }
    case "big_title": {
      const sc = t < IN * 0.6 ? 0.7 + 0.36 * (t / (IN * 0.6)) : t < IN ? 1.06 - 0.06 * ((t - IN * 0.6) / (IN * 0.4)) : 1;
      return frame({ left: left + w / 2, top: top + h * 0.45, transform: `translate(-50%,-50%) scale(${sc})`, textAlign: "center",
        textShadow: `0 0 ${6 * s}px #000, 0 ${4 * s}px ${4 * s}px #000` }, <>
        <div style={{ fontSize: 110 * s, lineHeight: 1.1 }}>{x.text}</div>
        {x.subtext && <div style={{ fontSize: 46 * s, color: x.accent }}>{x.subtext}</div>}
      </>);
    }
    case "top_banner": {
      const bh = 52 * s * 1.9;
      return frame({ left, top: top - bh * (1 - pin), width: w, height: bh, background: x.accent, display: "flex", alignItems: "center",
        justifyContent: x.align === "left" ? "flex-start" : x.align === "right" ? "flex-end" : "center", padding: `0 ${w * 0.05}px`, boxSizing: "border-box",
        boxShadow: `0 ${4 * s}px ${8 * s}px rgba(0,0,0,.4)` }, <span style={{ fontSize: 52 * s }}>
        {x.text}{x.subtext && <span style={{ fontWeight: 400, opacity: 0.75 }}>{"  "}{x.subtext}</span>}</span>);
    }
    case "subscribe": {
      const sc = t < IN * 0.6 ? 0.4 + 0.7 * (t / (IN * 0.6)) : t < IN ? 1.1 - 0.1 * ((t - IN * 0.6) / (IN * 0.4)) : 1;
      const anchor = x.align === "left" ? { left: left + w * 0.05 } : x.align === "center" ? { left: left + w / 2, translate: "-50% 0" } : { left: left + w * 0.95, translate: "-100% 0" };
      return frame({ ...anchor, top: top + h * 0.8, transform: `translateY(-100%) scale(${sc})`, textAlign: "center" } as React.CSSProperties, <>
        <div style={{ background: x.accent, borderRadius: 52 * s * 1.8 * 0.25, padding: `0 ${34 * s}px`, height: 52 * s * 1.8, lineHeight: `${52 * s * 1.8}px`,
          fontSize: 52 * s, boxShadow: `0 ${4 * s}px ${8 * s}px rgba(0,0,0,.4)` }}>{x.text || "SUBSCRIBE"}</div>
        {x.subtext && <div style={{ fontSize: 31 * s, color: "#fff", textShadow: "0 0 3px #000", marginTop: 10 * s }}>{x.subtext}</div>}
      </>);
    }
    case "death_card": {
      // export: titles.py _death_card (box bottom at 78 %, slides 60 px in over 0.14 s)
      const slide = -60 * s * (1 - Math.min(1, t / 0.14));
      const pad = 26 * s;
      return frame({ left: left + w * 0.05 + slide, top: top + h * 0.78, transform: "translateY(-100%)", background: "rgba(0,0,0,.84)",
        borderLeft: `${12 * s}px solid ${x.accent}`, borderRadius: 8 * s, padding: `${pad * 0.8}px ${pad}px ${pad * 0.7}px`,
        boxShadow: `${4 * s}px ${4 * s}px 0 rgba(0,0,0,.4)`, minWidth: 300 * s, opacity: Math.min(1, t / 0.15) }, <>
        <div style={{ fontSize: 30 * s, lineHeight: 1.35, color: x.accent, ...(x.font ? {} : { fontWeight: 700 }) }}>KILL #{killN || 1}</div>
        <div style={{ fontSize: 66 * s, lineHeight: 1.15 }}>{x.text}</div>
        {x.subtext && <div style={{ fontSize: 38 * s, lineHeight: 1.3, opacity: 0.8, fontWeight: x.font ? 400 : 400 }}>{x.subtext}</div>}
      </>);
    }
    case "number_card": {
      const sc = t < IN * 0.6 ? 0.4 + 0.72 * (t / (IN * 0.6)) : t < IN ? 1.12 - 0.12 * ((t - IN * 0.6) / (IN * 0.4)) : 1;
      const fs = 300 * s, cy = top + h * 0.42;
      const rise = (1 - Math.min(1, Math.max(0, (t - 0.15) / IN))) * h * 0.05;
      return <>
        {frame({ left, top, width: w, height: h, background: "rgba(0,0,0,.56)", opacity: Math.min(1, t / 0.2) }, null)}
        {frame({ left: left + w / 2, top: cy, transform: `translate(-50%,-50%) scale(${sc})`, fontSize: fs, lineHeight: 1, color: x.accent,
          WebkitTextStroke: `${10 * s * 2}px #000`, paintOrder: "stroke fill", textShadow: `${6 * s}px ${6 * s}px 0 rgba(0,0,0,.4)`,
          ...styleCss({ ...x, stroke: x.stroke }, s, k) }, `#${x.number ?? 1}`)}
        {x.text && frame({ left: left + w / 2, top: cy + fs * 0.55 + rise, transform: "translateX(-50%)", fontSize: 78 * s, lineHeight: 1.15,
          WebkitTextStroke: `${5 * s * 2}px #000`, paintOrder: "stroke fill", ...styleCss(x, s, k), opacity: Math.min(1, Math.max(0, (t - 0.15) / 0.15)) }, x.text)}
        {x.subtext && frame({ left: left + w / 2, top: cy + fs * 0.55 + 78 * s * 1.3, transform: "translateX(-50%)", fontSize: 42 * s, fontWeight: 400, opacity: 0.8 }, x.subtext)}
      </>;
    }
    case "tally": {
      const info = tally ?? { entries: [], total: 0 };
      const entries = info.entries.slice(0, 36), n = entries.length;
      const cols = n <= 8 ? 1 : n <= 18 ? 2 : 3, rows = Math.max(1, Math.ceil(n / cols));
      const fh = 64 * s, ft = 150 * s, topList = top + h * 0.07 + fh * 1.2 + ft * 1.15;
      const rowH = Math.min(36 * s * 1.4, (top + h * 0.95 - topList) / rows), fe = Math.min(36 * s, rowH / 1.4);
      const step = Math.min(0.25, Math.max(0.05, x.duration * 0.4 / Math.max(1, n)));
      const sc = t < 0.24 ? 0.4 + 0.72 * (t / 0.24) : t < 0.4 ? 1.12 - 0.12 * ((t - 0.24) / 0.16) : 1;
      const colW = w * 0.9 / cols;
      return <>
        {frame({ left, top, width: w, height: h, background: "rgba(0,0,0,.9)", opacity: Math.min(1, t / 0.25) }, null)}
        {frame({ left: left + w / 2, top: top + h * 0.07, transform: "translateX(-50%)", fontSize: fh, lineHeight: 1.2, opacity: Math.min(1, t / 0.25) }, x.text || "FINAL TALLY")}
        {frame({ left: left + w / 2, top: top + h * 0.07 + fh * 1.2, transform: `translateX(-50%) scale(${sc})`, transformOrigin: "50% 0", fontSize: ft, lineHeight: 1,
          color: x.accent, WebkitTextStroke: `${6 * s * 2}px #000`, paintOrder: "stroke fill" }, String(info.total))}
        {entries.map(([name, how], i) => {
          const c = Math.floor(i / rows), r = i % rows, t0 = 0.45 + i * step;
          return <React.Fragment key={i}>{frame({ left: left + w * 0.05 + c * colW + (cols === 1 ? colW / 2 : 0), top: topList + r * rowH,
            transform: cols === 1 ? "translateX(-50%)" : undefined, fontSize: fe, lineHeight: 1.2, opacity: Math.min(1, Math.max(0, (t - t0) / 0.18)) },
            <>{i + 1}. {name}{how && <span style={{ opacity: 0.7 }}>  — {how}</span>}</>)}</React.Fragment>;
        })}
      </>;
    }
    case "chapter":
      return frame({ left, top, width: w, height: h, background: "rgba(0,0,0,.69)", opacity: Math.min(1, t / IN), display: "flex",
        flexDirection: "column", alignItems: "center", justifyContent: "center", textAlign: "center" }, <>
        {x.subtext && <div style={{ fontSize: 40 * s, color: x.accent, textTransform: "uppercase" }}>{x.subtext}</div>}
        <div style={{ fontSize: 96 * s, lineHeight: 1.2 }}>{x.text}</div>
        <div style={{ width: 160 * s, height: 8 * s, background: x.accent, marginTop: 10 * s }} />
      </>);
  }
  return null;
}
