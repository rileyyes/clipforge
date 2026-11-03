// Canvas renderer used for the editor, small-size previews and the exported file —
// one code path, so what you see is exactly what gets exported.
import type { Design, ImageLayer, Layer, ShapeLayer, TextLayer } from "./model";

export type ImageMap = Map<string, HTMLImageElement>;

export function drawDesign(ctx: CanvasRenderingContext2D, d: Design, images: ImageMap, scale = 1) {
  ctx.save();
  ctx.setTransform(scale, 0, 0, scale, 0, 0);
  ctx.fillStyle = d.background;
  ctx.fillRect(0, 0, d.width, d.height);
  for (const l of d.layers) if (!l.hidden) drawLayer(ctx, l, images, scale);
  ctx.restore();
}

function drawLayer(ctx: CanvasRenderingContext2D, l: Layer, images: ImageMap, scale: number) {
  ctx.save();
  ctx.globalAlpha = l.opacity;
  ctx.translate(l.x + l.w / 2, l.y + l.h / 2);
  ctx.rotate((l.rotation * Math.PI) / 180);
  if (l.type === "image") drawImage(ctx, l, images, scale);
  else if (l.type === "text") drawText(ctx, l);
  else drawShape(ctx, l);
  ctx.restore();
}

function drawImage(ctx: CanvasRenderingContext2D, l: ImageLayer, images: ImageMap, scale: number) {
  const img = images.get(l.asset_id);
  const w = l.w, h = l.h;
  if (!img || !img.complete || !img.naturalWidth) {
    ctx.fillStyle = "#222";
    ctx.fillRect(-w / 2, -h / 2, w, h);
    return;
  }
  const sx = l.crop.x * img.naturalWidth, sy = l.crop.y * img.naturalHeight;
  const sw = l.crop.w * img.naturalWidth, sh = l.crop.h * img.naturalHeight;
  // never stretch: cover crops the source, contain letterboxes inside the box
  let dx = -w / 2, dy = -h / 2, dw = w, dh = h, cx = sx, cy = sy, cw = sw, ch = sh;
  const sr = sw / sh, br = w / h;
  if (l.fit === "cover") {
    if (sr > br) { cw = sh * br; cx = sx + (sw - cw) / 2; } else { ch = sw / br; cy = sy + (sh - ch) / 2; }
  } else {
    if (sr > br) { dh = w / sr; dy = -dh / 2; } else { dw = h * sr; dx = -dw / 2; }
  }
  const f = l.filters;
  ctx.filter = `brightness(${f.brightness}%) contrast(${f.contrast}%) saturate(${f.saturation}%)` + (f.blur ? ` blur(${f.blur * scale}px)` : "");
  ctx.beginPath();
  ctx.rect(-w / 2, -h / 2, w, h);
  ctx.clip();
  if (l.flip) ctx.scale(-1, 1);
  ctx.drawImage(img, cx, cy, cw, ch, dx, dy, dw, dh);
  ctx.filter = "none";
}

function drawText(ctx: CanvasRenderingContext2D, t: TextLayer) {
  const lines = (t.uppercase ? t.text.toUpperCase() : t.text).split("\n");
  ctx.font = `${t.font_weight} ${t.font_size}px "${t.font_family}", Impact, "Arial Black", sans-serif`;
  (ctx as any).letterSpacing = `${t.letter_spacing}px`;
  ctx.textBaseline = "middle";
  ctx.textAlign = t.align;
  const x = t.align === "left" ? -t.w / 2 + t.stroke_width : t.align === "right" ? t.w / 2 - t.stroke_width : 0;
  const lh = t.font_size * t.line_height;
  const top = -((lines.length - 1) * lh) / 2;
  ctx.lineJoin = "round";
  lines.forEach((line, i) => {
    const y = top + i * lh;
    if (t.shadow) {
      ctx.shadowColor = t.shadow.color; ctx.shadowBlur = t.shadow.blur;
      ctx.shadowOffsetX = t.shadow.dx; ctx.shadowOffsetY = t.shadow.dy;
    }
    if (t.stroke_width > 0) {
      ctx.strokeStyle = t.stroke_color;
      ctx.lineWidth = t.stroke_width * 2;
      ctx.strokeText(line, x, y);
      ctx.shadowColor = "transparent";
    }
    ctx.fillStyle = t.color;
    ctx.fillText(line, x, y);
    ctx.shadowColor = "transparent";
  });
}

function fillStyle(ctx: CanvasRenderingContext2D, s: ShapeLayer): string | CanvasGradient {
  if (s.gradient === "none" || !s.fill2) return s.fill;
  const w = s.w, h = s.h;
  if (s.gradient === "radial") {
    const g = ctx.createRadialGradient(0, 0, Math.min(w, h) * 0.25, 0, 0, Math.hypot(w, h) / 2);
    g.addColorStop(0, s.fill); g.addColorStop(1, s.fill2);
    return g;
  }
  const a = (s.gradient_angle * Math.PI) / 180;
  const r = (Math.abs(w * Math.cos(a)) + Math.abs(h * Math.sin(a))) / 2;
  const g = ctx.createLinearGradient(-Math.cos(a) * r, -Math.sin(a) * r, Math.cos(a) * r, Math.sin(a) * r);
  g.addColorStop(0, s.fill); g.addColorStop(1, s.fill2);
  return g;
}

function drawShape(ctx: CanvasRenderingContext2D, s: ShapeLayer) {
  const w = s.w, h = s.h;
  ctx.beginPath();
  if (s.shape === "ellipse") ctx.ellipse(0, 0, w / 2, h / 2, 0, 0, Math.PI * 2);
  else if (s.shape === "arrow") {
    const shaft = h * 0.36, head = Math.min(w * 0.4, h * 1.1);
    ctx.moveTo(-w / 2, -shaft / 2); ctx.lineTo(w / 2 - head, -shaft / 2); ctx.lineTo(w / 2 - head, -h / 2);
    ctx.lineTo(w / 2, 0); ctx.lineTo(w / 2 - head, h / 2); ctx.lineTo(w / 2 - head, shaft / 2); ctx.lineTo(-w / 2, shaft / 2);
    ctx.closePath();
  } else if (s.radius > 0 && (ctx as any).roundRect) (ctx as any).roundRect(-w / 2, -h / 2, w, h, Math.min(s.radius, w / 2, h / 2));
  else ctx.rect(-w / 2, -h / 2, w, h);
  ctx.fillStyle = fillStyle(ctx, s);
  ctx.fill();
  if (s.stroke && s.stroke_width > 0) { ctx.strokeStyle = s.stroke; ctx.lineWidth = s.stroke_width; ctx.stroke(); }
}

/** Load (and cache) the images a design needs. */
export function loadImages(urls: Map<string, string>, cache: ImageMap): Promise<void> {
  const jobs: Promise<void>[] = [];
  for (const [id, url] of urls) {
    if (cache.has(id)) continue;
    const img = new Image();
    cache.set(id, img);
    jobs.push(new Promise((res) => { img.onload = () => res(); img.onerror = () => res(); img.src = url; }));
  }
  return Promise.all(jobs).then(() => undefined);
}

/** Render at exactly 1280x720 and encode. JPEG quality steps down until it fits YouTube's 2 MB limit. */
export async function exportBlob(d: Design, images: ImageMap, format: "png" | "jpg"): Promise<Blob> {
  const c = document.createElement("canvas");
  c.width = d.width; c.height = d.height;
  drawDesign(c.getContext("2d")!, d, images, 1);
  const toBlob = (type: string, q?: number) => new Promise<Blob>((res, rej) => c.toBlob((b) => (b ? res(b) : rej(new Error("encode failed"))), type, q));
  if (format === "png") return toBlob("image/png");
  for (const q of [0.92, 0.85, 0.78, 0.7, 0.6]) {
    const b = await toBlob("image/jpeg", q);
    if (b.size <= 2 * 1024 * 1024) return b;
  }
  return toBlob("image/jpeg", 0.5);
}
