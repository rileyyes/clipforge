// CSS look-alikes of the export's transitions for the monitor (the export is exact).
// a = outgoing picture, b = incoming; p = 0..1 through the transition.
import type { CSSProperties } from "react";

export interface TransitionLook { a: CSSProperties; b: CSSProperties; aOnTop: boolean; overlay?: CSSProperties }

const ease = (x: number) => x * x * (3 - 2 * x);
const pct = (x: number) => `${(x * 100).toFixed(2)}%`;

export function transitionLook(kind: string, p: number): TransitionLook {
  const e = ease(p), bump = Math.sin(Math.PI * p);
  const fade = (extraA: CSSProperties = {}, extraB: CSSProperties = {}): TransitionLook =>
    ({ a: { opacity: 1 - p, ...extraA }, b: extraB, aOnTop: true });
  switch (kind) {
    case "dip_black": case "dip_white":
      return { a: { opacity: p < 0.5 ? 1 : 0 }, b: {}, aOnTop: true,
        overlay: { background: kind === "dip_black" ? "#000" : "#fff", opacity: 1 - Math.abs(p - 0.5) * 2 } };
    case "wipe_left": return { a: { clipPath: `inset(0 ${pct(p)} 0 0)` }, b: {}, aOnTop: true };
    case "wipe_right": return { a: { clipPath: `inset(0 0 0 ${pct(p)})` }, b: {}, aOnTop: true };
    case "wipe_up": return { a: { clipPath: `inset(0 0 ${pct(p)} 0)` }, b: {}, aOnTop: true };
    case "wipe_down": return { a: { clipPath: `inset(${pct(p)} 0 0 0)` }, b: {}, aOnTop: true };
    case "slide_left": case "smooth_left": { const q = kind === "smooth_left" ? e : p;
      return { a: { translate: `${pct(-q)} 0` }, b: { translate: `${pct(1 - q)} 0` }, aOnTop: true }; }
    case "slide_right": case "smooth_right": { const q = kind === "smooth_right" ? e : p;
      return { a: { translate: `${pct(q)} 0` }, b: { translate: `${pct(q - 1)} 0` }, aOnTop: true }; }
    case "slide_up": return { a: { translate: `0 ${pct(-p)}` }, b: { translate: `0 ${pct(1 - p)}` }, aOnTop: true };
    case "slide_down": return { a: { translate: `0 ${pct(p)}` }, b: { translate: `0 ${pct(p - 1)}` }, aOnTop: true };
    case "cover_left": return { a: {}, b: { translate: `${pct(1 - p)} 0` }, aOnTop: false };
    case "reveal_right": return { a: { translate: `${pct(p)} 0` }, b: {}, aOnTop: true };
    case "circle_open": return { a: {}, b: { clipPath: `circle(${pct(p * 0.75)} at 50% 50%)` }, aOnTop: false };
    case "circle_close": return { a: { clipPath: `circle(${pct((1 - p) * 0.75)} at 50% 50%)` }, b: {}, aOnTop: true };
    case "zoom_in": return fade({ scale: `${1 + p * 0.6}` });
    case "blur": case "pixelize": return fade({ filter: `blur(${(bump * 12).toFixed(1)}px)` }, { filter: `blur(${(bump * 12).toFixed(1)}px)` });
    case "whip_left": return { a: { translate: `${pct(-e)} 0`, filter: `blur(${(bump * 10).toFixed(1)}px)` }, b: { translate: `${pct(1 - e)} 0`, filter: `blur(${(bump * 10).toFixed(1)}px)` }, aOnTop: true };
    case "whip_right": return { a: { translate: `${pct(e)} 0`, filter: `blur(${(bump * 10).toFixed(1)}px)` }, b: { translate: `${pct(e - 1)} 0`, filter: `blur(${(bump * 10).toFixed(1)}px)` }, aOnTop: true };
    case "spin": return p < 0.5 ? { a: { rotate: `${180 * Math.pow(p, 2)}deg` }, b: { opacity: 0 }, aOnTop: true }
      : { a: { opacity: 0 }, b: { rotate: `${-180 * Math.pow(1 - p, 2)}deg` }, aOnTop: false };
    case "glitch": return fade({ translate: `${(Math.sin(p * 90) * 4 * bump).toFixed(1)}% 0` }, { translate: `${(Math.cos(p * 70) * 4 * bump).toFixed(1)}% 0` });
    case "rgb_split": return fade({ filter: `hue-rotate(${(bump * 90).toFixed(0)}deg) saturate(${1 + bump})` });
    case "light_leak": return { ...fade(), overlay: { background: "radial-gradient(circle at 78% 25%, rgba(255,160,64,.9), rgba(255,120,40,0) 60%)", opacity: bump * 0.85, mixBlendMode: "screen" } };
    case "zoom_blur": return p < 0.5 ? { a: { scale: `${1 + p * 1.6}`, filter: `blur(${(bump * 8).toFixed(1)}px)` }, b: { opacity: 0 }, aOnTop: true }
      : { a: { opacity: 0 }, b: { scale: `${1 + (1 - p) * 1.6}`, filter: `blur(${(bump * 8).toFixed(1)}px)` }, aOnTop: false };
    case "flash_cut": return { a: { opacity: p < 0.5 ? 1 : 0 }, b: {}, aOnTop: true, overlay: { background: "#fff", opacity: Math.max(0, 1 - Math.abs(p - 0.5) * 5) } };
    case "shake_cut": { const k = Math.max(0, 1 - Math.abs(p - 0.5) * 4), sh = `${(Math.sin(p * 71) * 3.5 * k).toFixed(2)}% ${(Math.cos(p * 53) * 3.5 * k).toFixed(2)}%`;
      return { a: { opacity: p < 0.5 ? 1 : 0, translate: sh, scale: `${1 + 0.08 * k}` }, b: { translate: sh, scale: `${1 + 0.08 * k}` }, aOnTop: true }; }
    default: return fade();  // crossfade, radial and anything new
  }
}
