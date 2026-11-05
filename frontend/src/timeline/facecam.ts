// Face cam geometry and timing for the preview. Mirrors backend/app/facecam.py
// (layout_box, cam_parts) and is checked against shared vectors from it.
import type { CamBox, FaceCam, MediaAsset, Timeline } from "./types";

export const HIDE_FADE = 0.25;

export function defaultFaceCam(media_id: string, main_media_id: string): FaceCam {
  return {
    enabled: true, media_id, main_media_id, offset: 0, corner: "bottom_right", size: 0.28, margin: 0.03,
    box: { x: 0.69, y: 0.6, w: 0.28, h: 0.3 }, crop: { left: 0, right: 0, top: 0, bottom: 0 },
    shape: "rounded", border: 0.004, border_color: "#ffffff", shadow: true, remove_bg: false, hidden: [], full: [],
  };
}

export function camAspect(fc: FaceCam, cam: MediaAsset | undefined, full = false): number {
  const w = cam?.width || 16, h = cam?.height || 9;
  if (full) return w / h;
  const c = fc.crop;
  return (w * (1 - c.left - c.right)) / Math.max(1e-6, h * (1 - c.top - c.bottom));
}

const r5 = (v: number) => Math.round(v * 1e5) / 1e5;

export function layoutBox(fc: FaceCam, W: number, H: number, aspect: number): CamBox {
  if (fc.corner === "custom") return fc.box;
  const mx = fc.margin;
  const my = Math.min(0.2, (fc.margin * W) / H);
  let bw = fc.size * W;
  let bh = fc.shape === "circle" ? bw : bw / Math.max(aspect, 1e-6);
  const room = H * (1 - 2 * my);
  if (bh > room) { const k = room / bh; bw *= k; bh *= k; }
  const w = bw / W, h = bh / H;
  const x = fc.corner.endsWith("left") ? mx : 1 - mx - w;
  const y = fc.corner.startsWith("top") ? my : 1 - my - h;
  return { x: r5(x), y: r5(y), w: r5(w), h: r5(h) };
}

export interface CamState { camTime: number; full: boolean; alpha: number; speed: number }

/** What the face cam shows at timeline time t (null: nothing). */
export function camAt(tl: Timeline, fc: FaceCam | null | undefined, cam: MediaAsset | undefined, t: number): CamState | null {
  if (!fc || !fc.enabled || !cam) return null;
  const track = tl.tracks.find((x) => x.kind === "video" && !x.hidden);
  if (!track) return null;
  const c = track.clips.find((k) => t >= k.start - 1e-9 && t < k.start + (k.source_out - k.source_in) / k.speed - 1e-9);
  if (!c || c.media_id !== fc.main_media_id) return null;
  const main = c.source_in + (t - c.start) * c.speed;
  const camTime = main + fc.offset;
  if (camTime < 0 || camTime > cam.duration) return null;
  if (fc.hidden.some((r) => main >= r.start && main < r.end)) return null;
  const full = fc.full.some((r) => main >= r.start && main < r.end);
  // fade next to hidden stretches (in timeline seconds, like the export)
  let alpha = 1;
  const clipEnd = c.source_out, clipStart = c.source_in;
  for (const r of fc.hidden) {
    if (r.end > clipStart && r.end <= main) alpha = Math.min(alpha, (main - r.end) / c.speed / HIDE_FADE);
    if (r.start < clipEnd && r.start > main) alpha = Math.min(alpha, (r.start - main) / c.speed / HIDE_FADE);
  }
  return { camTime, full, alpha: Math.max(0, Math.min(1, alpha)), speed: c.speed };
}
