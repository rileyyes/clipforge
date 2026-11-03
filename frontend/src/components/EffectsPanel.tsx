import React, { useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError, fmtTime, type Job } from "../api";
import { activeEffects, effectTime, newEffectAt } from "../timeline/effects";
import type { CaptionSettings, Effect, EffectKind, Sound, Timeline } from "../timeline/types";
import { Icon, JobRow, useToast } from "./ui";

const H = { "X-ClipForge": "1", "Content-Type": "application/json" };
async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const r = await fetch(path, { method, headers: H, body: body === undefined ? undefined : JSON.stringify(body) });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new ApiError(data.error || `Request failed (${r.status})`, r.status, data);
  return data;
}

const CENSOR_SOUNDS: Sound[] = ["beep", "boing", "scratch", "honk", "quack", "mute"];
const SFX: Sound[] = ["boom", "pop", "whoosh", "ding", "boing", "airhorn", "scratch", "honk", "quack"];
const KIND_LABEL: Record<EffectKind, string> = { censor: "Bleep", zoom: "Zoom", shake: "Shake", flash: "Flash", text: "Pop-up text", sfx: "Sound", image: "Image" };
const KIND_COLOR: Record<EffectKind, string> = { censor: "#ff5a6a", zoom: "#4cc9f0", shake: "#f2b84b", flash: "#ffffff", text: "#ffde00", sfx: "#2bb38a", image: "#c77dff" };
export const FX_COLOR = KIND_COLOR;

function playSound(s: Sound | null) {
  if (!s || s === "mute") return;
  new Audio(`/api/sounds/${s}.wav`).play().catch(() => {});
}

export default function EffectsPanel({ projectId, timeline, effects, captions, playhead, jobs, onJobs, setFx, seek }: {
  projectId: string; timeline: Timeline; effects: Effect[]; captions: CaptionSettings; playhead: number;
  jobs: Job[]; onJobs: () => void; seek: (t: number) => void;
  setFx: (effects: Effect[], captions: CaptionSettings, label: string) => void;
}) {
  const [status, setStatus] = useState<any>(null);
  const [sound, setSound] = useState<Sound>("beep");
  const [level, setLevel] = useState<"strong" | "all">("strong");
  const [custom, setCustom] = useState("");
  const [intensity, setIntensity] = useState<"minimal" | "balanced" | "chaotic">("balanced");
  const [images, setImages] = useState<string[]>([]);
  const [filter, setFilter] = useState<"all" | "censor" | "review">("all");
  const fileRef = useRef<HTMLInputElement>(null);
  const toast = useToast();

  const loadStatus = () => call<any>("GET", `/api/projects/${projectId}/fx/status`).then(setStatus).catch(() => {});
  const loadImages = () => call<any>("GET", `/api/projects/${projectId}/fx/images`).then((r) => setImages(r.images)).catch(() => {});
  useEffect(() => { loadStatus(); loadImages(); }, [projectId]);
  const tJob = jobs.find((j) => j.kind === "transcribe");
  const tActive = tJob && (tJob.status === "queued" || tJob.status === "running");
  useEffect(() => { if (tJob?.status === "succeeded") loadStatus(); }, [tJob?.status]);

  const rows = useMemo(() => effects.map((e) => ({ e, t: effectTime(timeline, e) }))
    .filter(({ e }) => filter === "all" || (filter === "censor" ? e.kind === "censor" : e.needs_review))
    .sort((a, b) => (a.t ?? 1e12) - (b.t ?? 1e12)), [effects, timeline, filter]);
  const counts = { censor: effects.filter((e) => e.kind === "censor").length, review: effects.filter((e) => e.needs_review && e.enabled).length };

  const replaceAuto = (kinds: (k: EffectKind) => boolean, incoming: Effect[], label: string) =>
    setFx([...effects.filter((e) => !(e.origin === "auto" && kinds(e.kind))), ...incoming], captions, label);
  const patch = (id: string, p: Partial<Effect>, label = "Edit effect") =>
    setFx(effects.map((e) => (e.id === id ? { ...e, ...p } : e)), captions, label);
  const add = (kind: EffectKind, extra: Partial<Effect> = {}) => {
    if (kind === "text" || kind === "image") {
      // don't stack on top of a pop-up that's already showing here
      const busy = activeEffects(timeline, effects, playhead + 0.05).some(({ e }) => (e.kind === "text" || e.kind === "image") && e.y < 0.5);
      if (busy && extra.y === undefined) extra = { ...extra, y: 0.72 };
    }
    const e = newEffectAt(timeline, playhead, kind, extra);
    if (!e) return toast("Move the playhead over a clip first", true);
    setFx([...effects, e], captions, `Add ${KIND_LABEL[kind]}`);
  };
  const cap = (p: Partial<CaptionSettings>) => setFx(effects, { ...captions, ...p }, "Caption settings");

  const tr = status?.transcript;
  return (
    <div className="pane-body" style={{ display: "grid", gap: 12, alignContent: "start" }}>
      {/* ---------------- transcript */}
      <div className="insp-section">
        <h3 style={{ margin: 0 }}>1 · Transcript</h3>
        {!status ? <span className="muted">…</span> : (<>
          <div style={{ fontSize: 12 }}>{tr.transcribed} of {tr.media_in_edit} clip source(s) transcribed{tr.missing.length === 0 && tr.media_in_edit > 0 ? " ✓" : ""}</div>
          {!status.transcriber ? (
            <div className="muted" style={{ fontSize: 12 }}>Speech-to-text isn't installed (needed for bleeps & captions). Free: in the <span className="mono">backend</span> folder run <span className="mono">pip install -r requirements-ai.txt</span> and restart ClipForge.</div>
          ) : (<>
            {tJob && tActive && <JobRow job={tJob} onChange={onJobs} />}
            {!tActive && <button className="btn sm" disabled={tr.media_in_edit === 0} onClick={async () => {
              try { await call("POST", `/api/projects/${projectId}/transcribe`, {}); onJobs(); } catch (e: any) { toast(e.message, true); }
            }}><Icon name="music" size={13} />{tr.missing.length ? "Transcribe speech" : "Re-transcribe"}</button>}
          </>)}
        </>)}
      </div>

      {/* ---------------- censor */}
      <div className="insp-section">
        <h3 style={{ margin: 0 }}>2 · Bleep swears</h3>
        <div className="insp-grid">
          <label className="field">Sound<div className="row"><select value={sound} onChange={(e) => setSound(e.target.value as Sound)}>{CENSOR_SOUNDS.map((s) => <option key={s}>{s}</option>)}</select>
            <button className="btn sm ghost" title="Preview" onClick={() => playSound(sound)}><Icon name="play" size={12} /></button></div></label>
          <label className="field">Words<select value={level} onChange={(e) => setLevel(e.target.value as any)}><option value="strong">Strong swears</option><option value="all">+ mild (damn, hell, crap)</option></select></label>
        </div>
        <label className="field">Extra words to bleep (comma separated)<input type="text" value={custom} onChange={(e) => setCustom(e.target.value)} placeholder="e.g. a name, a slang word" /></label>
        <button className="btn sm" disabled={!tr || tr.transcribed === 0} onClick={async () => {
          try {
            const r = await call<any>("POST", `/api/projects/${projectId}/fx/censor/suggest`, { sound, level, custom: custom.split(",").map((x) => x.trim()).filter(Boolean) });
            replaceAuto((k) => k === "censor", r.effects, "Find swears");
            const rev = r.effects.filter((e: Effect) => e.needs_review).length;
            toast(r.effects.length ? `${r.effects.length} bleep(s) added${rev ? ` — ${rev} need a check` : ""}` : "No swears found");
          } catch (e: any) { toast(e.message, true); }
        }}>Find & bleep swears</button>
        <div className="dim" style={{ fontSize: 11 }}>The original word is removed from the audio, not just covered. Captions show it masked. Speech recognition can miss or mishear words — review the list below.</div>
      </div>

      {/* ---------------- fun */}
      <div className="insp-section">
        <h3 style={{ margin: 0 }}>3 · Comedy edits</h3>
        <div className="row">
          <select value={intensity} onChange={(e) => setIntensity(e.target.value as any)}><option value="minimal">Minimal</option><option value="balanced">Balanced</option><option value="chaotic">Chaotic</option></select>
          <button className="btn sm" onClick={async () => {
            try {
              const r = await call<any>("POST", `/api/projects/${projectId}/fx/fun/suggest`, { intensity });
              replaceAuto((k) => k !== "censor", r.effects, "Suggest comedy edits");
              toast(r.effects.length ? `${r.effects.length} effect(s) placed on reactions` : "No strong reactions found");
            } catch (e: any) { toast(e.message, true); }
          }}><Icon name="wand" size={13} />Auto-place</button>
        </div>
        <div className="dim" style={{ fontSize: 11 }}>Zooms, shakes, pop-up text and sounds on the loudest reactions. Your images are only used where you place them.</div>
        <div className="row" style={{ flexWrap: "wrap", gap: 4 }}>
          <span className="muted" style={{ fontSize: 11 }}>Add at playhead:</span>
          {(["zoom", "shake", "flash", "text", "sfx", "censor"] as EffectKind[]).map((k) => (
            <button key={k} className="btn sm" onClick={() => add(k)}>{KIND_LABEL[k]}</button>
          ))}
          <select className="btn sm" value="" onChange={(e) => { if (e.target.value === "__up") fileRef.current?.click(); else if (e.target.value) add("image", { asset: e.target.value }); }}>
            <option value="">Image…</option>
            {images.map((i, n) => <option key={i} value={i}>Image {n + 1}</option>)}
            <option value="__up">Upload image…</option>
          </select>
          <input ref={fileRef} type="file" accept="image/png,image/jpeg,image/webp,image/gif" hidden onChange={async (e) => {
            const f = e.target.files?.[0]; e.target.value = "";
            if (!f) return;
            const r = await fetch(`/api/projects/${projectId}/fx/images`, { method: "POST", headers: { "X-ClipForge": "1" }, body: f });
            const d = await r.json();
            if (!r.ok) return toast(d.error, true);
            loadImages(); add("image", { asset: d.id });
          }} />
        </div>
      </div>

      {/* ---------------- captions */}
      <div className="insp-section">
        <h3 style={{ margin: 0 }}>4 · Captions</h3>
        <label className="row" style={{ fontSize: 12 }}><input type="checkbox" checked={captions.enabled} onChange={(e) => cap({ enabled: e.target.checked })} />Burn animated captions into the export</label>
        <div className="insp-grid">
          <label className="field">Style<select value={captions.style} onChange={(e) => cap({ style: e.target.value as any })}><option value="bold_pop">Bold pop</option><option value="highlight">Word highlight</option><option value="clean">Clean box</option></select></label>
          <label className="field">Position<select value={captions.position} onChange={(e) => cap({ position: e.target.value as any })}><option>bottom</option><option>middle</option><option>top</option></select></label>
          <label className="field">Words per line<input type="number" min={1} max={12} value={captions.max_words} onChange={(e) => cap({ max_words: Math.max(1, Math.min(12, +e.target.value || 4)) })} /></label>
          <label className="field">Size<input type="range" min={0.04} max={0.15} step={0.005} value={captions.size} onChange={(e) => cap({ size: +e.target.value })} /></label>
        </div>
        <a className="btn sm" href={`/api/projects/${projectId}/captions.srt`} download>Download .srt (for YouTube)</a>
      </div>

      {/* ---------------- list */}
      <div style={{ display: "grid", gap: 6 }}>
        <div className="row"><h3 style={{ margin: 0 }}>Effects ({effects.length})</h3><span className="spacer" />
          <select value={filter} onChange={(e) => setFilter(e.target.value as any)}>
            <option value="all">All</option><option value="censor">Bleeps ({counts.censor})</option><option value="review">Needs check ({counts.review})</option>
          </select></div>
        {rows.length === 0 && <div className="muted" style={{ fontSize: 12 }}>None yet.</div>}
        {rows.slice(0, 400).map(({ e, t }) => (
          <div key={e.id} style={{ border: "1px solid var(--line)", borderRadius: 8, padding: 8, display: "grid", gap: 6, opacity: e.enabled && t !== null ? 1 : 0.5, borderLeft: `3px solid ${KIND_COLOR[e.kind]}` }}>
            <div className="row" style={{ gap: 6 }}>
              <input type="checkbox" checked={e.enabled} title="Use this effect" onChange={(ev) => patch(e.id, { enabled: ev.target.checked, needs_review: false }, ev.target.checked ? "Enable effect" : "Disable effect")} />
              <strong style={{ fontSize: 12 }}>{KIND_LABEL[e.kind]}</strong>
              <button className="btn sm ghost mono" disabled={t === null} onClick={() => t !== null && seek(Math.max(0, t - 0.5))}>{t === null ? "cut from edit" : fmtTime(t)}</button>
              {e.needs_review && <span className="chip warn" title="Low confidence or very short word — check it">check</span>}
              <span className="spacer" />
              <button className="btn sm ghost danger" title="Delete" onClick={() => setFx(effects.filter((x) => x.id !== e.id), captions, "Delete effect")}><Icon name="trash" size={12} /></button>
            </div>
            {e.kind === "censor" && (<>
              <div style={{ fontSize: 12 }}>“{e.word}” {e.confidence != null && <span className="dim">({Math.round(e.confidence * 100)}% sure)</span>}</div>
              {e.context && <div className="dim" style={{ fontSize: 11 }}>…{e.context}…</div>}
            </>)}
            {(e.kind === "censor" || e.kind === "sfx") && (
              <div className="row"><select value={e.sound ?? ""} onChange={(ev) => patch(e.id, { sound: ev.target.value as Sound })}>{(e.kind === "censor" ? CENSOR_SOUNDS : SFX).map((s) => <option key={s}>{s}</option>)}</select>
                <button className="btn sm ghost" onClick={() => playSound(e.sound)}><Icon name="play" size={12} /></button>
                {e.kind === "censor" && <>
                  <button className="btn sm ghost" title="Start earlier" onClick={() => patch(e.id, { source_time: Math.max(0, e.source_time - 0.05), duration: e.duration + 0.05 })}>◀+</button>
                  <button className="btn sm ghost" title="End later" onClick={() => patch(e.id, { duration: Math.min(30, e.duration + 0.05) })}>+▶</button>
                </>}
              </div>
            )}
            {e.kind === "text" && <div className="row">
              <input type="text" maxLength={40} value={e.text ?? ""} onChange={(ev) => patch(e.id, { text: ev.target.value || " " })} />
              <input type="color" value={e.color} onChange={(ev) => patch(e.id, { color: ev.target.value })} />
            </div>}
            {(e.kind === "zoom") && <label className="field">Zoom {Math.round(e.scale * 100)}%<input type="range" min={1.05} max={2} step={0.05} value={e.scale} onChange={(ev) => patch(e.id, { scale: +ev.target.value })} /></label>}
            {(e.kind === "text" || e.kind === "image" || e.kind === "zoom") && (
              <div className="insp-grid">
                <label className="field">Across<input type="range" min={0} max={1} step={0.02} value={e.x} onChange={(ev) => patch(e.id, { x: +ev.target.value })} /></label>
                <label className="field">Down<input type="range" min={0} max={1} step={0.02} value={e.y} onChange={(ev) => patch(e.id, { y: +ev.target.value })} /></label>
              </div>
            )}
            {e.kind !== "censor" && e.kind !== "flash" && <label className="field">Length {e.duration.toFixed(1)}s<input type="range" min={0.2} max={5} step={0.1} value={e.duration} onChange={(ev) => patch(e.id, { duration: +ev.target.value })} /></label>}
          </div>
        ))}
      </div>
    </div>
  );
}
