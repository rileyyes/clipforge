// Thumbnail design model + pure editing operations (unit-tested in model.test.ts).
// Mirrors backend/app/thumb_models.py.

export interface Base { id: string; name: string; x: number; y: number; w: number; h: number; rotation: number; opacity: number; locked: boolean; hidden: boolean }
export interface Filters { brightness: number; contrast: number; saturation: number; blur: number }
export interface ImageLayer extends Base { type: "image"; asset_id: string; fit: "cover" | "contain"; crop: { x: number; y: number; w: number; h: number }; filters: Filters; flip: boolean }
export interface Shadow { color: string; blur: number; dx: number; dy: number }
export interface TextLayer extends Base { type: "text"; text: string; font_family: string; font_weight: number; font_size: number; align: "left" | "center" | "right"; letter_spacing: number; line_height: number; uppercase: boolean; color: string; stroke_color: string; stroke_width: number; shadow: Shadow | null }
export interface ShapeLayer extends Base { type: "shape"; shape: "rect" | "ellipse" | "arrow" | "highlight"; fill: string; fill2: string | null; gradient: "none" | "linear" | "radial"; gradient_angle: number; stroke: string | null; stroke_width: number; radius: number; role: "element" | "scrim" }
export type Layer = ImageLayer | TextLayer | ShapeLayer;

export interface Concept {
  id: string; name: string; hook: string; composition: string; subject: string; background: string; headline: string;
  palette: string[]; style: string; why: string; workflow: "ai_original" | "ai_with_footage" | "footage_composite";
  workflow_reason: string; image_prompt: string; negative_prompt: string; departs_from_footage: boolean; review_note: string;
  reference_frames: string[]; layout: string; direction: string; source: string;
}

export interface Design {
  id: string; name: string; width: number; height: number; background: string; layers: Layer[];
  concept: Concept | null; generations: any[]; edit_revision: number; timeline_fingerprint: string;
  timeline_coverage: [string, number, number][]; created_at: string; updated_at: string;
}

export const FONTS = ["Impact", "Arial Black", "Arial", "Segoe UI", "Helvetica", "Georgia", "Verdana", "Trebuchet MS", "Courier New", "Comic Sans MS"];

export function newId(): string {
  const c = (globalThis as any).crypto;
  if (c?.randomUUID) return c.randomUUID().replace(/-/g, "");
  return Array.from({ length: 32 }, () => Math.floor(Math.random() * 16).toString(16)).join("");
}

const base = (name: string, x: number, y: number, w: number, h: number): Base =>
  ({ id: newId(), name, x, y, w, h, rotation: 0, opacity: 1, locked: false, hidden: false });

export function makeText(text = "HEADLINE"): TextLayer {
  return { ...base("Text", 80, 260, 700, 150), type: "text", text, font_family: "Impact", font_weight: 900, font_size: 130,
    align: "left", letter_spacing: 0, line_height: 1, uppercase: true, color: "#ffffff", stroke_color: "#000000",
    stroke_width: 12, shadow: { color: "#000000cc", blur: 18, dx: 0, dy: 6 } };
}

export function makeShape(shape: ShapeLayer["shape"]): ShapeLayer {
  const s: ShapeLayer = { ...base(shape === "highlight" ? "Highlight" : shape === "arrow" ? "Arrow" : "Shape", 480, 260, 320, 200),
    type: "shape", shape, fill: "#ff3b30ff", fill2: null, gradient: "none", gradient_angle: 0, stroke: null, stroke_width: 0, radius: 0, role: "element" };
  if (shape === "highlight") { s.fill = "#00000000"; s.stroke = "#ffde00ff"; s.stroke_width = 10; s.radius = 24; }
  if (shape === "arrow") { s.h = 120; }
  return s;
}

export function makeImage(asset_id: string, name: string, w = 1280, h = 720): ImageLayer {
  return { ...base(name, 0, 0, w, h), type: "image", asset_id, fit: "cover", crop: { x: 0, y: 0, w: 1, h: 1 },
    filters: { brightness: 100, contrast: 100, saturation: 100, blur: 0 }, flip: false };
}

// ---------------------------------------------------------------- ops (immutable)
export type Result = { design: Design; error?: undefined } | { error: string; design?: undefined };
const find = (d: Design, id: string) => d.layers.findIndex((l) => l.id === id);
const lockedErr = (l?: Layer) => (l?.locked ? `“${l.name || l.type}” is locked` : null);

export function addLayer(d: Design, l: Layer, index?: number): Result {
  if (d.layers.length >= 60) return { error: "Layer limit reached (60)" };
  const layers = [...d.layers];
  layers.splice(index ?? layers.length, 0, l);
  return { design: { ...d, layers } };
}

export function updateLayer(d: Design, id: string, patch: Partial<Layer>, allowLocked = false): Result {
  const i = find(d, id);
  if (i < 0) return { error: "Layer not found" };
  const cur = d.layers[i];
  const onlyFlags = Object.keys(patch).every((k) => k === "locked" || k === "hidden" || k === "name");
  if (!allowLocked && !onlyFlags && cur.locked) return { error: lockedErr(cur)! };
  const next = { ...cur, ...patch } as Layer;
  if (next.w <= 0 || next.h <= 0) return { error: "Size must be positive" };
  const layers = [...d.layers];
  layers[i] = next;
  return { design: { ...d, layers } };
}

export function removeLayer(d: Design, id: string): Result {
  const i = find(d, id);
  if (i < 0) return { error: "Layer not found" };
  const le = lockedErr(d.layers[i]);
  if (le) return { error: le };
  return { design: { ...d, layers: d.layers.filter((l) => l.id !== id) } };
}

export function duplicateLayer(d: Design, id: string): Result {
  const i = find(d, id);
  if (i < 0) return { error: "Layer not found" };
  const copy = { ...structuredClone(d.layers[i]), id: newId(), x: d.layers[i].x + 24, y: d.layers[i].y + 24, locked: false, name: (d.layers[i].name || d.layers[i].type) + " copy" } as Layer;
  return addLayer(d, copy, i + 1);
}

export function moveLayerOrder(d: Design, id: string, dir: 1 | -1): Result {
  const i = find(d, id), j = i + dir;
  if (i < 0) return { error: "Layer not found" };
  if (j < 0 || j >= d.layers.length) return { design: d };
  const layers = [...d.layers];
  [layers[i], layers[j]] = [layers[j], layers[i]];
  return { design: { ...d, layers } };
}

/** Top-most visible, unlocked layer under a point (honours rotation). Scrims are skipped. */
export function hitTest(d: Design, px: number, py: number): Layer | null {
  for (let i = d.layers.length - 1; i >= 0; i--) {
    const l = d.layers[i];
    if (l.hidden || (l.type === "shape" && l.role === "scrim")) continue;
    const cx = l.x + l.w / 2, cy = l.y + l.h / 2;
    const a = (-l.rotation * Math.PI) / 180;
    const dx = px - cx, dy = py - cy;
    const rx = dx * Math.cos(a) - dy * Math.sin(a), ry = dx * Math.sin(a) + dy * Math.cos(a);
    if (Math.abs(rx) <= l.w / 2 && Math.abs(ry) <= l.h / 2) return l;
  }
  return null;
}

/** Shrink-wrap a text layer's box to its content (approximate metrics, refined by the renderer). */
export function fitTextBox(t: TextLayer, measure?: (line: string) => number): TextLayer {
  const lines = (t.uppercase ? t.text.toUpperCase() : t.text).split("\n");
  const width = Math.max(40, ...lines.map((l) => (measure ? measure(l) : l.length * t.font_size * 0.58) + Math.max(0, l.length - 1) * t.letter_spacing)) + t.stroke_width * 2;
  return { ...t, w: Math.round(width), h: Math.round(lines.length * t.font_size * t.line_height + t.stroke_width * 2) };
}
