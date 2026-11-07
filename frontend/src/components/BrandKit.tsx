import React, { useEffect, useRef, useState } from "react";
import { Icon, useToast } from "./ui";

export interface BrandCaptions { style: "clean" | "bold_pop" | "highlight"; color: string; highlight: string; position: "bottom" | "middle" | "top"; size: number; uppercase: boolean }
export interface Brand {
  name: string; logo: string | null; logo_corner: "tl" | "tr" | "bl" | "br"; logo_size: number; logo_opacity: number;
  intro: string | null; outro: string | null; title_color: string; title_accent: string; captions: BrandCaptions;
}
export interface BrandPayload { brand: Brand; has_logo: boolean; has_intro: boolean; has_outro: boolean }

const H = { "X-RJClip": "1" };
export const brandApi = {
  get: async (): Promise<BrandPayload> => (await fetch("/api/brand")).json(),
  async put(b: Brand): Promise<BrandPayload> {
    const r = await fetch("/api/brand", { method: "PUT", headers: { ...H, "Content-Type": "application/json" }, body: JSON.stringify(b) });
    const d = await r.json(); if (!r.ok) throw new Error(d.error); return d;
  },
  async file(kind: "logo" | "intro" | "outro", f: File): Promise<BrandPayload> {
    const r = await fetch(`/api/brand/files/${kind}?filename=${encodeURIComponent(f.name)}`, { method: "POST", headers: H, body: f });
    const d = await r.json(); if (!r.ok) throw new Error(d.error); return d;
  },
  async remove(kind: "logo" | "intro" | "outro"): Promise<BrandPayload> {
    const r = await fetch(`/api/brand/files/${kind}`, { method: "DELETE", headers: H });
    const d = await r.json(); if (!r.ok) throw new Error(d.error); return d;
  },
};

/** Settings → Brand kit: set it up once, then apply it to any video from the Editor (Text tab). */
export default function BrandKit() {
  const toast = useToast();
  const [p, setP] = useState<BrandPayload | null>(null);
  const [v, setV] = useState(0);   // bust the logo image cache after an upload
  const timer = useRef<number | undefined>(undefined);
  useEffect(() => { brandApi.get().then(setP).catch(() => toast("Couldn't load the brand kit", true)); }, []);
  if (!p) return <div className="card"><h3>Brand kit</h3><span className="muted">Loading…</span></div>;
  const b = p.brand;
  const set = (patch: Partial<Brand>) => {
    const next = { ...p, brand: { ...b, ...patch } };
    setP(next);
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => brandApi.put(next.brand).then(setP).catch((e) => toast(e.message, true)), 400);
  };
  const upload = (kind: "logo" | "intro" | "outro", accept: string) => {
    const inp = document.createElement("input");
    inp.type = "file"; inp.accept = accept;
    inp.onchange = async () => {
      const f = inp.files?.[0]; if (!f) return;
      try { setP(await brandApi.file(kind, f)); setV((x) => x + 1); toast(`${kind[0].toUpperCase() + kind.slice(1)} saved`); }
      catch (e: any) { toast(e.message, true); }
    };
    inp.click();
  };
  const fileRow = (kind: "intro" | "outro", has: boolean) => (
    <div className="row" style={{ gap: 6 }}>
      <span style={{ width: 52 }}>{kind === "intro" ? "Intro" : "Outro"}</span>
      <span className="dim grow" style={{ fontSize: 12 }}>{has ? "✓ saved" : "none"}</span>
      <button className="btn sm" onClick={() => upload(kind, "video/*,.mp4,.mov,.mkv,.webm")}><Icon name="upload" size={13} />{has ? "Replace" : "Choose video"}</button>
      {has && <button className="btn sm ghost" aria-label={`Remove ${kind}`} onClick={async () => setP(await brandApi.remove(kind))}><Icon name="trash" size={13} /></button>}
    </div>
  );
  return (
    <div className="card" data-testid="brand-kit" style={{ display: "grid", gap: 10 }}>
      <h3 style={{ margin: 0 }}>Brand kit</h3>
      <p className="muted" style={{ fontSize: 12, margin: 0 }}>Set your look once. In the Editor, <b>Text</b> tab → <b>Apply my brand kit</b> adds it to a video.</p>
      <div className="row" style={{ gap: 10, alignItems: "flex-start" }}>
        <div className="brand-logo">{p.has_logo ? <img src={`/api/brand/logo?v=${v}`} alt="Your logo" /> : <span className="dim">No logo</span>}</div>
        <div style={{ display: "grid", gap: 6, flex: 1, minWidth: 0 }}>
          <div className="row" style={{ gap: 6 }}>
            <button className="btn sm" onClick={() => upload("logo", "image/png,image/jpeg,image/webp")}><Icon name="upload" size={13} />{p.has_logo ? "Replace logo" : "Upload logo"}</button>
            {p.has_logo && <button className="btn sm ghost" aria-label="Remove logo" onClick={async () => setP(await brandApi.remove("logo"))}><Icon name="trash" size={13} /></button>}
          </div>
          <div className="dim" style={{ fontSize: 11 }}>A PNG with a see-through background looks best.</div>
          <div className="row" style={{ gap: 6 }}>
            <select aria-label="Logo corner" value={b.logo_corner} onChange={(e) => set({ logo_corner: e.target.value as Brand["logo_corner"] })}>
              <option value="tl">Top left</option><option value="tr">Top right</option><option value="bl">Bottom left</option><option value="br">Bottom right</option>
            </select>
            <label className="row" style={{ gap: 4, fontSize: 12, flex: 1 }}>Size
              <input type="range" aria-label="Logo size" min={0.05} max={0.3} step={0.01} value={b.logo_size} onChange={(e) => set({ logo_size: +e.target.value })} style={{ flex: 1 }} /></label>
            <label className="row" style={{ gap: 4, fontSize: 12, flex: 1 }}>See-through
              <input type="range" aria-label="Logo opacity" min={0.2} max={1} step={0.05} value={b.logo_opacity} onChange={(e) => set({ logo_opacity: +e.target.value })} style={{ flex: 1 }} /></label>
          </div>
        </div>
      </div>
      {fileRow("intro", p.has_intro)}
      {fileRow("outro", p.has_outro)}
      <div className="row" style={{ gap: 10, flexWrap: "wrap" }}>
        <label className="row" style={{ gap: 4, fontSize: 12 }}>Title text <input type="color" aria-label="Brand title colour" value={b.title_color} onChange={(e) => set({ title_color: e.target.value })} /></label>
        <label className="row" style={{ gap: 4, fontSize: 12 }}>Title accent <input type="color" aria-label="Brand accent colour" value={b.title_accent} onChange={(e) => set({ title_accent: e.target.value })} /></label>
      </div>
      <div className="row" style={{ gap: 6, flexWrap: "wrap", fontSize: 12 }}>
        Captions
        <select aria-label="Brand caption style" value={b.captions.style} onChange={(e) => set({ captions: { ...b.captions, style: e.target.value as BrandCaptions["style"] } })}>
          <option value="bold_pop">Bold pop</option><option value="clean">Clean box</option><option value="highlight">Word highlight</option>
        </select>
        <select aria-label="Brand caption position" value={b.captions.position} onChange={(e) => set({ captions: { ...b.captions, position: e.target.value as BrandCaptions["position"] } })}>
          <option value="bottom">Bottom</option><option value="middle">Middle</option><option value="top">Top</option>
        </select>
        <input type="color" aria-label="Brand caption colour" value={b.captions.color} onChange={(e) => set({ captions: { ...b.captions, color: e.target.value } })} />
        <input type="color" aria-label="Brand caption highlight" value={b.captions.highlight} onChange={(e) => set({ captions: { ...b.captions, highlight: e.target.value } })} />
        <label className="row" style={{ gap: 4 }}><input type="checkbox" checked={b.captions.uppercase} onChange={(e) => set({ captions: { ...b.captions, uppercase: e.target.checked } })} />CAPS</label>
      </div>
    </div>
  );
}
