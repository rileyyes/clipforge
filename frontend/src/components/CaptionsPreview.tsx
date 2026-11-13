import { fontCss } from "../fonts";
import React from "react";
import { captionAt, keyWord, type CapChunk } from "../timeline/captions";
import type { CaptionSettings } from "../timeline/types";

/** A CSS look-alike of the burned-in captions (export: backend/app/effects.py captions_ass,
 *  libass). Same lines and timing, size (relative to the output height), position and
 *  side margins; the outline and pop are close, not pixel-exact. */
export default function CaptionsPreview({ chunks, cs, t, k, W, H, ox, oy }: {
  chunks: CapChunk[]; cs: CaptionSettings; t: number; k: number; W: number; H: number; ox: number; oy: number;
}) {
  const on = captionAt(chunks, t);
  if (!on) return null;
  const { chunk, word } = on;
  const kw = cs.emphasis ? keyWord(chunk.words.map((w) => w.text)) : null;
  const size = Math.round(H * cs.size) * k;
  const w = W * k, h = H * k, side = W * 0.06 * k;
  const margin = H * (cs.position !== "middle" ? 0.08 : 0) * k;
  const outline = (cs.style === "clean" ? Math.max(2, size / k / 10) : Math.max(3, size / k / 9)) * k;
  const age = t - chunk.start;
  const pop = cs.style === "bold_pop" ? (age < 0.09 ? 0.8 + (1.12 - 0.8) * (age / 0.09) : age < 0.17 ? 1.12 - 0.12 * ((age - 0.09) / 0.08) : 1) : 1;
  const fade = cs.style === "highlight" ? 1 : Math.min(1, age / (cs.style === "clean" ? 0.06 : 0.04), (chunk.end - t) / 0.06);
  const pos: React.CSSProperties = cs.position === "bottom" ? { bottom: oy + margin, top: "auto" }
    : cs.position === "top" ? { top: oy + margin } : { top: oy + h / 2, transform: "translateY(-50%)" };
  const text: React.CSSProperties = cs.style === "clean"
    ? { background: "rgba(0,0,0,.56)", padding: `${outline * 0.5}px ${outline}px`, borderRadius: 2, boxDecorationBreak: "clone", WebkitBoxDecorationBreak: "clone" }
    : { WebkitTextStroke: `${outline * 2}px #000`, paintOrder: "stroke fill", textShadow: `${outline * 0.7}px ${outline * 0.7}px 0 rgba(0,0,0,.6)` };
  return (
    <div data-testid="caption-preview" data-style={cs.style} style={{ position: "absolute", left: ox + side, width: w - 2 * side, ...pos,
      textAlign: "center", pointerEvents: "none", zIndex: 1500, opacity: Math.max(0, fade) }}>
      <span style={{ display: "inline-block", transform: `scale(${pop})`, transformOrigin: "50% 100%" }}>
        <span style={{ fontFamily: fontCss(cs.font), fontWeight: cs.font ? 400 : 700, fontSize: size, lineHeight: 1.18, color: cs.color, ...text }}>
          {cs.style === "highlight" || kw !== null
            ? chunk.words.map((x, i) => <React.Fragment key={i}>{i > 0 && " "}<span data-key-word={i === kw ? "1" : undefined}
                style={{ color: cs.style === "highlight" && i === word ? cs.highlight : i === kw ? cs.emphasis_color ?? "#00e5ff" : cs.color,
                  ...(i === kw ? { display: "inline-block", transform: "scale(1.15)", margin: `0 ${size * 0.06}px` } : {}) }}>{x.text}</span></React.Fragment>)
            : chunk.text}
        </span>
      </span>
    </div>
  );
}
