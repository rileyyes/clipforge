import React from "react";
import type { Title } from "../timeline/types";

/** CSS versions of the title templates for the monitor (export: backend/app/titles.py, libass).
 *  Same sizes (relative to the output height), positions and in/out timing. */
const IN = 0.4, OUT = 0.3;
const ease = (x: number) => 1 - Math.pow(1 - Math.min(1, Math.max(0, x)), 3);

export default function TitlesPreview({ titles, t, k, W, H, ox, oy }: {
  titles: Title[]; t: number; k: number; W: number; H: number; ox: number; oy: number;
}) {
  const on = titles.filter((x) => t >= x.start && t < x.start + x.duration).sort((a, b) => a.start - b.start);
  return <>{on.map((x) => <One key={x.id} x={x} t={t - x.start} k={k} W={W} H={H} ox={ox} oy={oy} />)}</>;
}

function One({ x, t, k, W, H, ox, oy }: { x: Title; t: number; k: number; W: number; H: number; ox: number; oy: number }) {
  const s = (H / 1080) * x.size * k;             // px on screen per design px at 1080p
  const fadeOut = Math.min(1, Math.max(0, (x.duration - t) / OUT));
  const pin = ease(t / IN);
  const base: React.CSSProperties = { position: "absolute", pointerEvents: "none", fontFamily: "'DejaVu Sans', Arial, sans-serif", fontWeight: 700, color: x.color, whiteSpace: "nowrap" };
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
