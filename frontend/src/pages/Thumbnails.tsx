import React, { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, api } from "../api";
import { Icon, JobRow, useJobs, useToast } from "../components/ui";
import { History } from "../timeline/history";
import {
  FONTS, addLayer, duplicateLayer, fitTextBox, hitTest, makeShape, makeText, moveLayerOrder, removeLayer, updateLayer,
  type Concept, type Design, type Layer, type Result, type TextLayer,
} from "../thumbs/model";
import { drawDesign, exportBlob, loadImages, type ImageMap } from "../thumbs/render";
import Projects from "./Projects";

const H = { "X-ClipForge": "1", "Content-Type": "application/json" };
async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const r = await fetch(path, { method, headers: H, body: body === undefined ? undefined : JSON.stringify(body) });
  if (r.status === 204) return undefined as T;
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new ApiError(data.error || `Request failed (${r.status})`, r.status, data);
  return data;
}
const assetUrl = (pid: string, aid: string) => `/api/projects/${pid}/thumbnails/assets/${aid}`;
const GENRES = ["", "gaming", "horror", "funny", "commentary", "reaction", "documentary", "educational", "tutorial", "vlog", "cinematic", "minimalist", "professional"];
const WF_LABEL: Record<string, string> = { ai_original: "AI artwork", ai_with_footage: "AI art + your footage", footage_composite: "Your footage" };

// ---------------------------------------------------------------- canvas
function Canvas({ design, images, scale, selected, onSelect, onMove, version }: {
  design: Design; images: ImageMap; scale: number; selected?: string | null; version: number;
  onSelect?: (id: string | null) => void; onMove?: (id: string, x: number, y: number, done: boolean) => void;
}) {
  const ref = useRef<HTMLCanvasElement>(null);
  const drag = useRef<{ id: string; ox: number; oy: number; x0: number; y0: number } | null>(null);
  useEffect(() => {
    const c = ref.current!;
    const ctx = c.getContext("2d")!;
    drawDesign(ctx, design, images, scale);
    const l = design.layers.find((x) => x.id === selected);
    if (l && onSelect) {
      ctx.save(); ctx.scale(scale, scale);
      ctx.translate(l.x + l.w / 2, l.y + l.h / 2); ctx.rotate((l.rotation * Math.PI) / 180);
      ctx.strokeStyle = l.locked ? "#f2b84b" : "#4cc9f0"; ctx.lineWidth = 3 / scale; ctx.setLineDash([10 / scale, 6 / scale]);
      ctx.strokeRect(-l.w / 2, -l.h / 2, l.w, l.h); ctx.restore();
    }
  }, [design, images, scale, selected, version]);
  const pt = (e: React.PointerEvent) => {
    const r = ref.current!.getBoundingClientRect();
    return { x: ((e.clientX - r.left) / r.width) * design.width, y: ((e.clientY - r.top) / r.height) * design.height };
  };
  return (
    <canvas ref={ref} width={Math.round(design.width * scale)} height={Math.round(design.height * scale)}
      style={{ width: "100%", maxWidth: design.width * scale, borderRadius: 6, cursor: onSelect ? "move" : "default", touchAction: "none", background: "#000" }}
      onPointerDown={(e) => {
        if (!onSelect) return;
        const p = pt(e);
        const hit = hitTest(design, p.x, p.y);
        onSelect(hit?.id ?? null);
        if (hit && !hit.locked && onMove) {
          drag.current = { id: hit.id, ox: hit.x, oy: hit.y, x0: p.x, y0: p.y };
          (e.target as HTMLElement).setPointerCapture(e.pointerId);
        }
      }}
      onPointerMove={(e) => { const d = drag.current; if (d && onMove) { const p = pt(e); onMove(d.id, Math.round(d.ox + p.x - d.x0), Math.round(d.oy + p.y - d.y0), false); } }}
      onPointerUp={(e) => { const d = drag.current; drag.current = null; if (d && onMove) { const p = pt(e); onMove(d.id, Math.round(d.ox + p.x - d.x0), Math.round(d.oy + p.y - d.y0), true); } }} />
  );
}

// ---------------------------------------------------------------- studio
function Studio({ pid, designId, onClose }: { pid: string; designId: string; onClose: () => void }) {
  const [design, setDesign] = useState<Design | null>(null);
  const [versions, setVersions] = useState<any[]>([]);
  const [stale, setStale] = useState<any>(null);
  const [sel, setSel] = useState<string | null>(null);
  const [imgVer, setImgVer] = useState(0);
  const [saving, setSaving] = useState<"saved" | "pending" | "error">("saved");
  const [instruction, setInstruction] = useState("");
  const [refineNote, setRefineNote] = useState<string[]>([]);
  const [exportRes, setExportRes] = useState<any>(null);
  const [fmt, setFmt] = useState<"jpg" | "png">("jpg");
  const images = useRef<ImageMap>(new Map()).current;
  const hist = useRef(new History<Design>()).current;
  const dragStart = useRef<Design | null>(null);
  const dirty = useRef(false);
  const toast = useToast();
  const [, force] = useState(0);

  const load = useCallback(async () => {
    const doc = await call<any>("GET", `/api/projects/${pid}/thumbnails/designs/${designId}`);
    setDesign(doc.draft); setVersions(doc.versions); setStale(doc.staleness);
  }, [pid, designId]);
  useEffect(() => { load().catch((e) => toast(e.message, true)); }, [load]);
  useEffect(() => {
    if (!design) return;
    const urls = new Map(design.layers.filter((l) => l.type === "image").map((l: any) => [l.asset_id, assetUrl(pid, l.asset_id)]));
    loadImages(urls, images).then(() => setImgVer((v) => v + 1));
  }, [design?.layers.map((l: any) => l.asset_id).join()]);

  // autosave the draft (versions are only created by "Save version")
  useEffect(() => {
    if (!design || !dirty.current) return;
    setSaving("pending");
    const t = setTimeout(() => {
      call("PUT", `/api/projects/${pid}/thumbnails/designs/${design.id}`, design)
        .then(() => { dirty.current = false; setSaving("saved"); })
        .catch((e) => { setSaving("error"); toast(e.message, true); });
    }, 600);
    return () => clearTimeout(t);
  }, [design]);

  const apply = (r: Result, label = "Edit") => {
    if (r.error !== undefined) { toast(r.error, true); return; }
    hist.push(design!, label); dirty.current = true; setDesign(r.design); force((n) => n + 1);
  };
  const live = (r: Result) => { if (r.design) { dirty.current = true; setDesign(r.design); } };
  const layer = design?.layers.find((l) => l.id === sel) ?? null;
  const upd = (patch: Partial<Layer>, label = "Edit") => layer && apply(updateLayer(design!, layer.id, patch), label);
  const updText = (patch: Partial<TextLayer>) => {
    if (!layer || layer.type !== "text") return;
    apply(updateLayer(design!, layer.id, fitTextBox({ ...(layer as TextLayer), ...patch }) as any), "Edit text");
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).closest("input, textarea, select")) return;
      const mod = e.ctrlKey || e.metaKey;
      if (mod && e.key.toLowerCase() === "z") { e.preventDefault(); const r = e.shiftKey ? hist.redo(design!) : hist.undo(design!); if (r) { dirty.current = true; setDesign(r.state); } }
      else if (mod && e.key.toLowerCase() === "d" && sel) { e.preventDefault(); apply(duplicateLayer(design!, sel), "Duplicate"); }
      else if ((e.key === "Delete" || e.key === "Backspace") && sel) { e.preventDefault(); apply(removeLayer(design!, sel), "Delete"); setSel(null); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  if (!design) return <div className="muted">Loading design…</div>;

  const doExport = async () => {
    setExportRes(null);
    try {
      const blob = await exportBlob(design, images, fmt);
      const r = await fetch(`/api/projects/${pid}/thumbnails/designs/${design.id}/export?format=${fmt}`, { method: "POST", headers: { "X-ClipForge": "1" }, body: blob });
      const data = await r.json();
      setExportRes(data);
      if (!r.ok) toast(data.error, true);
    } catch (e: any) { toast(e.message, true); }
  };

  const fs = (k: keyof NonNullable<any>, label: string, min = 0, max = 200) => layer?.type === "image" && (
    <label className="field">{label} <span className="mono">{(layer as any).filters[k]}</span>
      <input type="range" min={min} max={max} value={(layer as any).filters[k]}
        onPointerDown={() => { dragStart.current = design; }}
        onChange={(e) => live(updateLayer(design, layer.id, { filters: { ...(layer as any).filters, [k]: +e.target.value } } as any))}
        onPointerUp={() => { if (dragStart.current) { hist.push(dragStart.current, "Adjust"); dragStart.current = null; force((n) => n + 1); } }} />
    </label>
  );

  return (
    <div className="grid" style={{ gap: 14 }}>
      <div className="row">
        <button className="btn" onClick={onClose}><Icon name="prev" size={14} />All thumbnails</button>
        <input className="ed-title" value={design.name} maxLength={80}
          onChange={(e) => { dirty.current = true; setDesign({ ...design, name: e.target.value || "Thumbnail" }); }} />
        <span className="save-state"><span className={"dot" + (saving === "saved" ? "" : saving === "error" ? " bad" : " busy")} />{saving === "saved" ? "Draft saved" : saving === "error" ? "Save failed" : "Saving draft…"}</span>
        <span className="spacer" />
        <button className="btn icon ghost" title="Undo (Ctrl+Z)" disabled={!hist.canUndo} onClick={() => { const r = hist.undo(design); if (r) { dirty.current = true; setDesign(r.state); } }}><Icon name="undo" /></button>
        <button className="btn icon ghost" title="Redo (Ctrl+Shift+Z)" disabled={!hist.canRedo} onClick={() => { const r = hist.redo(design); if (r) { dirty.current = true; setDesign(r.state); } }}><Icon name="redo" /></button>
      </div>
      {stale && stale.state !== "current" && <div className={"banner" + (stale.state === "changed" ? " err" : "")} style={{ borderRadius: 8 }}><Icon name="warn" size={14} />{stale.message}</div>}
      {design.concept?.departs_from_footage && <div className="banner" style={{ borderRadius: 8 }}><Icon name="warn" size={14} />Contains AI artwork. {design.concept.review_note}</div>}

      <div className="grid" style={{ gridTemplateColumns: "minmax(0, 1fr) 300px", alignItems: "start" }}>
        <div className="grid" style={{ gap: 10 }}>
          <Canvas design={design} images={images} scale={0.62} selected={sel} version={imgVer} onSelect={setSel}
            onMove={(id, x, y, done) => {
              if (!dragStart.current) dragStart.current = design;
              const r = updateLayer(design, id, { x, y });
              if (done) { if (r.design && dragStart.current) { hist.push(dragStart.current, "Move"); dirty.current = true; setDesign(r.design); } dragStart.current = null; force((n) => n + 1); }
              else live(r);
            }} />
          <div className="row" style={{ alignItems: "end", gap: 16 }}>
            <div><div className="muted" style={{ fontSize: 11 }}>Home feed (~320px)</div><div style={{ width: 320 }}><Canvas design={design} images={images} scale={0.25} version={imgVer} /></div></div>
            <div><div className="muted" style={{ fontSize: 11 }}>Sidebar (~168px)</div><div style={{ width: 168 }}><Canvas design={design} images={images} scale={0.13125} version={imgVer} /></div></div>
            <span className="spacer" />
          </div>
          <div className="card grid" style={{ gap: 8 }}>
            <h3 style={{ margin: 0 }}>Refine in plain words</h3>
            <form className="row" onSubmit={async (e) => {
              e.preventDefault();
              if (!instruction.trim()) return;
              try {
                const r = await call<any>("POST", `/api/projects/${pid}/thumbnails/refine`, { design, instruction });
                if (r.applied.length) apply({ design: r.design }, `Refine: ${instruction}`);
                setRefineNote([...r.applied.map((a: string) => "✓ " + a), ...r.notes]);
                setInstruction("");
              } catch (err: any) { toast(err.message, true); }
            }}>
              <input type="text" className="grow" placeholder="e.g. more dramatic · remove the text · make the subject bigger · cleaner" value={instruction} onChange={(e) => setInstruction(e.target.value)} />
              <button className="btn">Apply</button>
            </form>
            {refineNote.map((n) => <div key={n} className="muted" style={{ fontSize: 12 }}>{n}</div>)}
          </div>
        </div>

        <div className="grid" style={{ gap: 12 }}>
          <div className="card grid" style={{ gap: 6 }}>
            <div className="row"><h3 style={{ margin: 0 }}>Layers</h3><span className="spacer" />
              <button className="btn sm" onClick={() => { const t = fitTextBox(makeText()); apply(addLayer(design, t), "Add text"); setSel(t.id); }}>+ Text</button>
              <button className="btn sm" onClick={() => { const s = makeShape("highlight"); apply(addLayer(design, s), "Add shape"); setSel(s.id); }}>+ Shape</button>
            </div>
            {[...design.layers].reverse().map((l) => (
              <div key={l.id} className="row" onClick={() => setSel(l.id)} style={{ padding: "4px 6px", borderRadius: 6, cursor: "pointer", background: sel === l.id ? "var(--panel-3)" : undefined, opacity: l.hidden ? 0.5 : 1, fontSize: 12 }}>
                <span className="ellipsis grow">{l.name || l.type}{l.type === "text" ? `: ${(l as TextLayer).text.replace("\n", " ")}` : ""}</span>
                <button className="btn sm ghost" title={l.hidden ? "Show" : "Hide"} onClick={(e) => { e.stopPropagation(); apply(updateLayer(design, l.id, { hidden: !l.hidden }), "Toggle"); }}><Icon name={l.hidden ? "eyeoff" : "eye"} size={13} /></button>
                <button className="btn sm ghost" title={l.locked ? "Unlock" : "Lock"} onClick={(e) => { e.stopPropagation(); apply(updateLayer(design, l.id, { locked: !l.locked }), "Lock"); }}><Icon name={l.locked ? "lock" : "unlock"} size={13} /></button>
              </div>
            ))}
          </div>
          {layer && (
            <div className="card grid" style={{ gap: 8 }}>
              <div className="row"><h3 style={{ margin: 0 }}>{layer.type}</h3><span className="spacer" />
                <button className="btn sm ghost" title="Bring forward" onClick={() => apply(moveLayerOrder(design, layer.id, 1), "Reorder")}>▲</button>
                <button className="btn sm ghost" title="Send back" onClick={() => apply(moveLayerOrder(design, layer.id, -1), "Reorder")}>▼</button>
                <button className="btn sm ghost" title="Duplicate (Ctrl+D)" onClick={() => apply(duplicateLayer(design, layer.id), "Duplicate")}><Icon name="copy" size={13} /></button>
                <button className="btn sm ghost danger" title="Delete" onClick={() => { apply(removeLayer(design, layer.id), "Delete"); setSel(null); }}><Icon name="trash" size={13} /></button>
              </div>
              {layer.locked && <span className="chip warn">Locked — unlock to edit</span>}
              {layer.type === "text" && (<>
                <textarea rows={2} value={(layer as TextLayer).text} maxLength={200} onChange={(e) => updText({ text: e.target.value })} style={{ background: "var(--bg)", color: "var(--text)", border: "1px solid var(--line-2)", borderRadius: 6, padding: 6 }} />
                <div className="insp-grid">
                  <label className="field">Font<select value={(layer as TextLayer).font_family} onChange={(e) => updText({ font_family: e.target.value })}>{FONTS.map((f) => <option key={f}>{f}</option>)}</select></label>
                  <label className="field">Size<input type="number" min={8} max={600} value={(layer as TextLayer).font_size} onChange={(e) => updText({ font_size: Math.max(8, Math.min(600, +e.target.value || 8)) })} /></label>
                  <label className="field">Colour<input type="color" value={(layer as TextLayer).color.slice(0, 7)} onChange={(e) => updText({ color: e.target.value })} /></label>
                  <label className="field">Outline<input type="color" value={(layer as TextLayer).stroke_color.slice(0, 7)} onChange={(e) => updText({ stroke_color: e.target.value })} /></label>
                  <label className="field">Outline width<input type="number" min={0} max={60} value={(layer as TextLayer).stroke_width} onChange={(e) => updText({ stroke_width: Math.max(0, Math.min(60, +e.target.value || 0)) })} /></label>
                  <label className="field">Align<select value={(layer as TextLayer).align} onChange={(e) => updText({ align: e.target.value as any })}><option>left</option><option>center</option><option>right</option></select></label>
                </div>
              </>)}
              {layer.type === "image" && (<>{fs("brightness", "Brightness", 20, 200)}{fs("contrast", "Contrast", 20, 200)}{fs("saturation", "Saturation", 0, 200)}{fs("blur", "Blur", 0, 20)}</>)}
              {layer.type === "shape" && (
                <label className="field">Colour<input type="color" value={((layer as any).stroke && (layer as any).stroke_width ? (layer as any).stroke : (layer as any).fill).slice(0, 7)}
                  onChange={(e) => upd((layer as any).stroke && (layer as any).stroke_width ? { stroke: e.target.value + "ff" } as any : { fill: e.target.value + "ff" } as any)} /></label>
              )}
              <div className="insp-grid">
                <div className="field"><span>Size</span><div className="row">
                  {[0.9, 1.1].map((f) => (
                    <button key={f} className="btn sm" onClick={() => { const cx = layer.x + layer.w / 2, cy = layer.y + layer.h / 2;
                      const patch: any = { w: layer.w * f, h: layer.h * f, x: cx - layer.w * f / 2, y: cy - layer.h * f / 2 };
                      if (layer.type === "text") patch.font_size = Math.max(8, Math.min(600, (layer as TextLayer).font_size * f));
                      upd(patch, "Resize"); }}>{f < 1 ? "− Smaller" : "+ Bigger"}</button>))}
                </div></div>
                <label className="field">Rotation<input type="number" min={-180} max={180} value={layer.rotation} onChange={(e) => upd({ rotation: Math.max(-180, Math.min(180, +e.target.value || 0)) }, "Rotate")} /></label>
              </div>
            </div>
          )}
          <div className="card grid" style={{ gap: 8 }}>
            <h3 style={{ margin: 0 }}>Versions</h3>
            <button className="btn sm" onClick={async () => {
              const label = prompt("Name this version", `Version ${versions.length + 1}`);
              if (label === null) return;
              try { await call("PUT", `/api/projects/${pid}/thumbnails/designs/${design.id}`, design); dirty.current = false; await call("POST", `/api/projects/${pid}/thumbnails/designs/${design.id}/versions`, { label }); await load(); toast("Version saved"); }
              catch (e: any) { toast(e.message, true); }
            }}>Save version</button>
            {versions.slice().reverse().map((v) => (
              <div key={v.id} className="row" style={{ fontSize: 12 }}>
                <span className="ellipsis grow">{v.label}</span>
                <button className="btn sm ghost" onClick={async () => { if (!confirm(`Replace the current draft with “${v.label}”? (The version itself is kept.)`)) return; const d = await call<Design>("POST", `/api/projects/${pid}/thumbnails/designs/${design.id}/versions/${v.id}/restore`); hist.push(design, "Restore"); setDesign(d); }}>Open</button>
              </div>
            ))}
          </div>
          <div className="card grid" style={{ gap: 8 }}>
            <h3 style={{ margin: 0 }}>Export</h3>
            <div className="row"><select value={fmt} onChange={(e) => setFmt(e.target.value as any)}><option value="jpg">JPEG (smaller)</option><option value="png">PNG</option></select>
              <button className="btn primary" onClick={doExport}><Icon name="export" size={14} />Export 1280×720</button></div>
            {exportRes?.validation && (
              <div className="checks">{exportRes.validation.checks.map((c: any) => (
                <div key={c.check} style={{ gridTemplateColumns: "18px 110px 1fr" }}><span style={{ color: c.ok ? "var(--ok)" : "var(--err)" }}>{c.ok ? "✓" : "✗"}</span><span>{c.check}</span><span className="muted mono" style={{ fontSize: 11 }}>{c.detail}</span></div>))}</div>
            )}
            {exportRes?.file && <a className="btn sm" href={`/api/projects/${pid}/thumbnails/exports/${encodeURIComponent(exportRes.file)}`} download>Download {exportRes.file}</a>}
          </div>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- workspace
function Workspace({ pid }: { pid: string }) {
  const [st, setSt] = useState<any>(null);
  const [ctx, setCtx] = useState<any>({ title: "", description: "", about: "", subject: "", genre: "", style_notes: "" });
  const [concepts, setConcepts] = useState<Concept[] | null>(null);
  const [headlines, setHeadlines] = useState<any[]>([]);
  const [need, setNeed] = useState<string | null>(null);
  const [seed, setSeed] = useState(0);
  const [consent, setConsent] = useState(false);
  const [openId, setOpenId] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const { jobs, refresh } = useJobs(pid);
  const toast = useToast();
  const load = () => call<any>("GET", `/api/projects/${pid}/thumbnails`).then((s) => { setSt(s); setCtx((c: any) => ({ ...c, ...s.context })); }).catch((e) => toast(e.message, true));
  useEffect(() => { load(); }, [pid]);
  const aJob = jobs.find((j) => j.kind === "thumb_analyze");
  const gJob = jobs.find((j) => j.kind === "thumb_generate");
  useEffect(() => { if (aJob?.status === "succeeded") load(); }, [aJob?.status]);

  if (openId) return <div className="page" style={{ maxWidth: 1400 }}><Studio pid={pid} designId={openId} onClose={() => { setOpenId(null); load(); }} /></div>;
  if (!st) return <div className="page muted">Loading…</div>;
  const analysis = st.analysis;
  const prov = st.image_provider;

  const getConcepts = async (s = seed) => {
    setBusy("concepts");
    try {
      const r = await call<any>("POST", `/api/projects/${pid}/thumbnails/concepts`, { context: ctx, seed: s });
      if (r.needs_context) { setNeed(r.needs_context.reason); setConcepts(null); }
      else { setNeed(null); setConcepts(r.concepts); setHeadlines(r.headlines); }
    } catch (e: any) { toast(e.message, true); } finally { setBusy(null); }
  };
  const create = async (c: Concept, workflow: Concept["workflow"], art?: string) => {
    try {
      const doc = await call<any>("POST", `/api/projects/${pid}/thumbnails/designs`, { concept: c, workflow, art_asset: art ?? null, name: c.name });
      setOpenId(doc.draft.id);
    } catch (e: any) { toast(e.message, true); }
  };
  const generate = async (c: Concept) => {
    try {
      const job = await call<any>("POST", `/api/projects/${pid}/thumbnails/generate`, { concept: c, use_references: c.workflow === "ai_with_footage", consent_external: consent });
      refresh();
      setBusy("generate:" + c.id);
      for (;;) {
        await new Promise((r) => setTimeout(r, 1000));
        const j = await call<any>("GET", `/api/jobs/${job.id}`);
        if (j.status === "succeeded") { setBusy(null); return create(c, c.workflow, j.result.asset_id); }
        if (!["queued", "running"].includes(j.status)) { setBusy(null); toast(j.error || "Generation failed", true); return; }
      }
    } catch (e: any) { setBusy(null); toast(e.message, true); }
  };

  return (
    <div className="page" style={{ maxWidth: 1400 }}>
      <div className="row" style={{ marginBottom: 14 }}>
        <div className="grow"><h1>Thumbnail Maker</h1><div className="muted">Based on your final edit · 1280×720 · free & local by default</div></div>
        <a className="btn" href="#/thumbs/">Change project</a>
      </div>
      <div className="grid" style={{ gridTemplateColumns: "360px minmax(0, 1fr)", alignItems: "start" }}>
        <div className="grid">
          <div className="card grid" style={{ gap: 8 }}>
            <h3 style={{ margin: 0 }}>AI artwork</h3>
            {prov ? <div style={{ fontSize: 12 }}><span className="chip ok">{prov.label}</span> {prov.external ? "External service — asks before sending anything." : "Runs on your computer."}<div className="dim" style={{ marginTop: 4 }}>Integration not yet tested against the real service.</div></div>
              : <div className="muted" style={{ fontSize: 12 }}>Not set up — thumbnails are built from your footage. Free option: {st.setup_help.sdwebui}</div>}
          </div>
          <div className="card grid" style={{ gap: 8 }}>
            <h3 style={{ margin: 0 }}>1 · Look at the final edit</h3>
            {st.timeline_empty ? <div className="muted">The timeline is empty. <a href={`#/editor/${pid}`}>Edit the video</a> or use the AI Auto Editor first.</div> : (<>
              {aJob && ["queued", "running"].includes(aJob.status) && <JobRow job={aJob} onChange={refresh} />}
              {analysis ? (<>
                <div className="muted" style={{ fontSize: 12 }}>{analysis.final_duration.toFixed(0)}s edit · {analysis.clip_count} clips · confidence <b>{analysis.confidence}</b>{analysis.format_guess ? ` · looks like ${analysis.format_guess}` : ""}</div>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 4 }}>
                  {analysis.moments.filter((m: any) => m.frame_asset).slice(0, 8).map((m: any) => (
                    <img key={m.frame_asset} src={assetUrl(pid, m.frame_asset)} title={`${m.time}s — ${m.reason}`} style={{ width: "100%", aspectRatio: "16/9", objectFit: "cover", borderRadius: 4 }} />))}
                </div>
                {analysis.unknowns.length > 0 && <div className="dim" style={{ fontSize: 11 }}>Not known from analysis: {analysis.unknowns.join("; ")}.</div>}
              </>) : <div className="muted" style={{ fontSize: 12 }}>Pulls representative frames from the current edit (trims, order and overlays applied).</div>}
              {!(aJob && ["queued", "running"].includes(aJob.status)) && <button className="btn" onClick={async () => { try { await call("POST", `/api/projects/${pid}/thumbnails/analyze`); refresh(); } catch (e: any) { toast(e.message, true); } }}>{analysis ? "Re-analyse edit" : "Analyse edit"}</button>}
            </>)}
          </div>
          <div className="card grid" style={{ gap: 8 }}>
            <h3 style={{ margin: 0 }}>2 · Tell it about the video</h3>
            <label className="field">What is the video about?<input type="text" maxLength={500} value={ctx.about} onChange={(e) => setCtx({ ...ctx, about: e.target.value })} placeholder="e.g. surviving my first night in a horror game" /></label>
            <label className="field">Video title (optional)<input type="text" maxLength={150} value={ctx.title} onChange={(e) => setCtx({ ...ctx, title: e.target.value })} /></label>
            <div className="insp-grid">
              <label className="field">Genre<select value={ctx.genre} onChange={(e) => setCtx({ ...ctx, genre: e.target.value })}>{GENRES.map((g) => <option key={g} value={g}>{g || "auto"}</option>)}</select></label>
              <label className="field">Main subject<input type="text" maxLength={200} value={ctx.subject} onChange={(e) => setCtx({ ...ctx, subject: e.target.value })} /></label>
            </div>
            {need && <div className="banner" style={{ borderRadius: 8 }}>{need}</div>}
            <button className="btn primary" disabled={!analysis || busy === "concepts"} onClick={() => getConcepts()}><Icon name="wand" size={14} />Get 3 concepts</button>
          </div>
        </div>

        <div className="grid">
          {concepts && (
            <div className="card grid" style={{ gap: 10 }}>
              <div className="row"><h3 style={{ margin: 0 }}>3 · Pick a concept</h3><span className="spacer" />
                <button className="btn sm" onClick={() => { setSeed(seed + 1); getConcepts(seed + 1); }}>New ideas</button></div>
              {prov?.external && <label className="row" style={{ fontSize: 12 }}><input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} />I agree to send the prompt (and, for “AI art + your footage”, selected frames) to {prov.label}.</label>}
              <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 10 }}>
                {concepts.map((c) => (
                  <div key={c.id} style={{ border: "1px solid var(--line)", borderRadius: 10, padding: 12, display: "grid", gap: 6, alignContent: "start" }}>
                    <div className="row"><strong>{c.name}</strong><span className="spacer" /><span className={"chip" + (c.workflow === "footage_composite" ? " ok" : " run")}>{WF_LABEL[c.workflow]}</span></div>
                    <div style={{ fontSize: 12 }}>{c.hook}</div>
                    <div className="muted" style={{ fontSize: 11 }}>{c.composition}</div>
                    {c.headline && <div style={{ fontFamily: "Impact, sans-serif", fontSize: 18 }}>“{c.headline}”</div>}
                    <div className="row" style={{ gap: 4 }}>{c.palette.map((p) => <span key={p} title={p} style={{ width: 18, height: 18, borderRadius: 4, background: p, border: "1px solid var(--line-2)" }} />)}</div>
                    <div className="dim" style={{ fontSize: 11 }}>{c.why}</div>
                    {c.review_note && <div className="chip warn" style={{ whiteSpace: "normal" }}>{c.review_note}</div>}
                    <div className="dim" style={{ fontSize: 11 }}>{c.workflow_reason}</div>
                    <button className="btn sm" disabled={!(analysis?.moments || []).some((m: any) => m.frame_asset)} onClick={() => create(c, "footage_composite")}>Build from my footage</button>
                    {c.workflow !== "footage_composite" && (
                      <button className="btn sm primary" disabled={!prov || busy?.startsWith("generate") || (prov?.external && !consent)}
                        title={!prov ? "Set up an image provider first" : ""} onClick={() => generate(c)}>
                        {busy === "generate:" + c.id ? "Generating…" : "Generate AI artwork"}</button>
                    )}
                  </div>
                ))}
              </div>
              {gJob && ["queued", "running"].includes(gJob.status) && <JobRow job={gJob} onChange={refresh} />}
              {headlines.length > 0 && <div style={{ fontSize: 12 }}><span className="muted">Headline ideas: </span>{headlines.map((h) => <span key={h.text} className="chip" title={h.basis} style={{ marginRight: 4 }}>{h.text}</span>)}</div>}
            </div>
          )}
          <div className="card">
            <h3>Saved thumbnails</h3>
            {st.designs.length === 0 && <div className="muted" style={{ fontSize: 12 }}>None yet.</div>}
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", gap: 10 }}>
              {st.designs.map((d: any) => (
                <div key={d.id} className="proj-card" onClick={() => setOpenId(d.id)}>
                  <div className="proj-thumb" style={d.preview_asset ? { backgroundImage: `url(${assetUrl(pid, d.preview_asset)})` } : {}} />
                  <div className="proj-meta"><strong className="ellipsis">{d.name}</strong>
                    <span className="muted" style={{ fontSize: 11 }}>{d.versions} version(s){d.timeline_fingerprint && st.fingerprint && d.timeline_fingerprint !== st.fingerprint ? " · edit changed since" : ""}</span>
                    <div className="row"><button className="btn sm ghost" onClick={async (e) => { e.stopPropagation(); await call("POST", `/api/projects/${pid}/thumbnails/designs/${d.id}/duplicate`); load(); }}>Duplicate</button>
                      <button className="btn sm ghost danger" onClick={async (e) => { e.stopPropagation(); if (!confirm(`Delete “${d.name}” and its versions?`)) return; await call("DELETE", `/api/projects/${pid}/thumbnails/designs/${d.id}`); load(); }}>Delete</button></div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export default function Thumbnails({ projectId }: { projectId?: string }) {
  return projectId ? <Workspace key={projectId} pid={projectId} /> : <Projects pickFor={"thumbs" as any} />;
}
