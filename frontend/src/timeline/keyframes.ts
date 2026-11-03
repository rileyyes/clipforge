// Keyframe interpolation — must match backend/app/look.py exactly (tests mirror both).
import type { Clip, ColorAdjust, Crop, KfProp, Keyframe, Look } from "./types";

export const KF_LIMITS: Record<KfProp, [number, number]> = {
  scale: [0.02, 10], x: [-10000, 10000], y: [-10000, 10000], rotation: [-3600, 3600], opacity: [0, 1], volume: [0, 4],
};
export const NO_CROP: Crop = { left: 0, right: 0, top: 0, bottom: 0 };
export const NO_COLOR: ColorAdjust = { brightness: 0, contrast: 1, saturation: 1, gamma: 1, temperature: 0, look: "none" };

export function valueAt(kfs: Keyframe[] | undefined, t: number, dflt: number): number {
  if (!kfs || !kfs.length) return dflt;
  if (t <= kfs[0].t) return kfs[0].v;
  for (let i = 0; i < kfs.length - 1; i++) {
    const a = kfs[i], b = kfs[i + 1];
    if (t < b.t) {
      let p = (t - a.t) / (b.t - a.t);
      const ease = a.ease ?? "linear";
      if (ease === "hold") return a.v;
      if (ease === "ease") p = p * p * (3 - 2 * p);
      return a.v + (b.v - a.v) * p;
    }
  }
  return kfs[kfs.length - 1].v;
}

/** Source-media time shown at timeline time ``t`` for this clip. */
export const sourceAt = (c: Clip, t: number) => c.source_in + (t - c.start) * c.speed;

export function staticValue(c: Clip, prop: KfProp): number {
  if (prop === "volume") return c.volume;
  if (prop === "opacity") return c.transform.opacity ?? 1;
  return c.transform[prop];
}

/** Property value at timeline time ``t`` (keyframes win over the static value). */
export function propAt(c: Clip, prop: KfProp, t: number): number {
  return valueAt(c.keyframes?.[prop], sourceAt(c, t), staticValue(c, prop));
}

const clamp = (v: number, [lo, hi]: [number, number]) => Math.max(lo, Math.min(hi, v));
const r6 = (v: number) => Math.round(v * 1e6) / 1e6;

/** Insert or replace the keyframe at source time ``t`` (within 1 frame-ish = 10 ms). */
export function setKeyframe(kfs: Keyframe[] | undefined, prop: KfProp, t: number, v: number, ease?: Keyframe["ease"]): Keyframe[] {
  const list = [...(kfs ?? [])];
  const k: Keyframe = { t: r6(Math.max(0, t)), v: r6(clamp(v, KF_LIMITS[prop])) };
  const i = list.findIndex((x) => Math.abs(x.t - k.t) < 0.01);
  if (i >= 0) list[i] = { ...list[i], v: k.v, ...(ease ? { ease } : {}) };
  else list.push({ ...k, ...(ease ? { ease } : {}) });
  list.sort((a, b) => a.t - b.t);
  return list.slice(0, 64);
}

export function removeKeyframe(kfs: Keyframe[] | undefined, t: number): Keyframe[] {
  return (kfs ?? []).filter((x) => Math.abs(x.t - t) >= 0.01);
}

export function keyframeNear(kfs: Keyframe[] | undefined, t: number): Keyframe | undefined {
  return (kfs ?? []).find((x) => Math.abs(x.t - t) < 0.01);
}

// ---------------------------------------------------------------- preview styling (approximate)
const LOOK_CSS: Record<Look, string> = {
  none: "", warm: "sepia(0.22) saturate(1.15)", cool: "hue-rotate(-12deg) saturate(0.9) brightness(1.02)",
  bw: "grayscale(1)", vintage: "sepia(0.45) contrast(0.9) saturate(0.85)", vivid: "saturate(1.35) contrast(1.08)",
  faded: "contrast(0.84) saturate(0.8) brightness(1.04)", cinematic: "contrast(1.08) saturate(0.9) hue-rotate(-6deg)",
  noir: "grayscale(1) contrast(1.35)",
};

/** CSS filter approximating the colour settings (the export uses the exact FFmpeg filters). */
export function colorCss(c?: ColorAdjust): string {
  if (!c) return "";
  const f: string[] = [];
  if (c.brightness) f.push(`brightness(${(1 + c.brightness).toFixed(3)})`);
  if (c.contrast !== 1) f.push(`contrast(${c.contrast.toFixed(3)})`);
  if (c.saturation !== 1) f.push(`saturate(${c.saturation.toFixed(3)})`);
  if (c.gamma !== 1) f.push(`brightness(${(Math.pow(0.5, 1 / c.gamma) / 0.5).toFixed(3)})`); // mid-grey shift
  if (c.temperature > 0) f.push(`sepia(${(c.temperature * 0.35).toFixed(3)})`);
  if (c.temperature < 0) f.push(`hue-rotate(${(c.temperature * 18).toFixed(1)}deg) saturate(${(1 + c.temperature * 0.1).toFixed(3)})`);
  if (LOOK_CSS[c.look]) f.push(LOOK_CSS[c.look]);
  return f.join(" ");
}

export function cropCss(c?: Crop): string | undefined {
  if (!c || (!c.left && !c.right && !c.top && !c.bottom)) return undefined;
  const p = (v: number) => `${(v * 100).toFixed(3)}%`;
  return `inset(${p(c.top)} ${p(c.right)} ${p(c.bottom)} ${p(c.left)})`;
}

/** Times (timeline seconds) of every keyframe of a clip that falls inside it — for markers. */
export function keyframeTimes(c: Clip): number[] {
  const out = new Set<number>();
  for (const list of Object.values(c.keyframes ?? {})) for (const k of list ?? []) {
    const tt = c.start + (k.t - c.source_in) / c.speed;
    if (k.t >= c.source_in - 1e-6 && k.t <= c.source_out + 1e-6) out.add(Math.round(tt * 1000) / 1000);
  }
  return [...out].sort((a, b) => a - b);
}
