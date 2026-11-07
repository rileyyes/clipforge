import React, { useEffect, useState } from "react";
import { ApiError, fmtTime, type Job } from "../api";
import { addBlur, blurAt, clipAt, removeBlur, sourceTimeAt, updateBlur, type OpResult } from "../timeline/ops";
import type { Blur, Timeline } from "../timeline/types";
import { Icon, JobRow, useToast } from "./ui";

const H = { "X-RJClip": "1", "Content-Type": "application/json" };
async function post<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(path, { method: "POST", headers: H, body: JSON.stringify(body) });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new ApiError(d.error || `Request failed (${r.status})`, r.status, d);
  return d;
}

/** Editor → Blur: hide faces, licence plates, chat windows… optionally following them. */
export default function BlurPanel({ projectId, timeline, playhead, seek, commit, drawing, setDrawing, jobs, onJobs, sel, setSel }: {
  projectId: string; timeline: Timeline; playhead: number; seek: (t: number) => void;
  commit: (r: OpResult, label: string, coalesce?: boolean) => boolean;
  drawing: null | { onBox: (b: { x: number; y: number; w: number; h: number }) => void };
  setDrawing: (d: null | { onBox: (b: { x: number; y: number; w: number; h: number }) => void }) => void;
  jobs: Job[]; onJobs: () => void; sel: string | null; setSel: (id: string | null) => void;
}) {
  const toast = useToast();
  const blurs = [...(timeline.blurs ?? [])].sort((a, b) => a.start - b.start);
  const [trackJob, setTrackJob] = useState<{ job: string; blur: string } | null>(null);
  const cur = blurs.find((b) => b.id === sel) ?? null;
  const set = (patch: Partial<Blur>, label: string) => cur && commit(updateBlur(timeline, cur.id, patch), label, true);
  const v1 = timeline.tracks.find((t) => t.kind === "video" && !t.hidden);

  // tracking finished: put the keys on the blur
  const tj = jobs.find((j) => j.id === trackJob?.job);
  useEffect(() => {
    if (!tj || !trackJob) return;
    if (tj.status === "succeeded") {
      const r = tj.result as { keys: Blur["keys"]; lost: number; frames: number };
      commit(updateBlur(timeline, trackJob.blur, { keys: r.keys }), "Track blur");
      toast(r.lost > r.frames * 0.2 ? `Followed it, but lost sight of it in ${r.lost} of ${r.frames} frames — check the preview`
        : `Following it now (${r.keys.length} positions)`, r.lost > r.frames * 0.2);
      setTrackJob(null);
    } else if (tj.status === "failed" || tj.status === "cancelled") setTrackJob(null);
  }, [tj?.status]);

  useEffect(() => () => setDrawing(null), []);

  const startDraw = (onBox: (b: { x: number; y: number; w: number; h: number }) => void) => {
    setDrawing({ onBox: (b) => { setDrawing(null); onBox(b); } });
  };
  const track = async (b: Blur) => {
    if (!v1) return;
    const a = b.start, e = b.start + b.duration;
    const pieces = v1.clips.filter((c) => c.start < e && c.start + (c.source_out - c.source_in) / c.speed > a).sort((x, y) => x.start - y.start).map((c) => {
      const t0 = Math.max(a, c.start), t1 = Math.min(e, c.start + (c.source_out - c.source_in) / c.speed);
      return { media_id: c.media_id, src_start: sourceTimeAt(c, t0), src_end: sourceTimeAt(c, t1), speed: c.speed, t_start: t0,
        scale: c.transform?.scale ?? 1, x: c.transform?.x ?? 0, y: c.transform?.y ?? 0 };
    }).filter((p) => p.src_end - p.src_start > 0.05);
    if (!pieces.length) return toast("There's no video under this blur to follow", true);
    const k = blurAt(b, a);
    try {
      const j = await post<Job>(`/api/projects/${projectId}/blur/track`, { pieces, box: { x: k.x, y: k.y, w: k.w, h: k.h } });
      setTrackJob({ job: j.id, blur: b.id }); onJobs();
    } catch (err: any) { toast(err.message, true); }
  };

  return (
    <div className="pane-body" style={{ display: "grid", gap: 12, alignContent: "start" }} data-testid="blur-panel">
      <div className="insp-section" style={{ marginBottom: 0 }}>
        <h3 style={{ margin: 0 }}>Hide something</h3>
        <div className="muted" style={{ fontSize: 12 }}>Blur a face, a licence plate, a chat window or anything private. It can follow what moves.</div>
        <div className="row" style={{ gap: 4, flexWrap: "wrap" }}>
          <button className={"btn sm" + (drawing ? " on" : "")} onClick={() => drawing ? setDrawing(null) : startDraw((box) => {
            const r = addBlur(timeline, playhead, box);
            if (commit(r, "Add blur") && r.id) { setSel(r.id); toast("Blur added for 3 s — set its length, or press Follow it"); }
          })}><Icon name="pencil" size={13} />{drawing ? "Drag on the picture… (click to cancel)" : "Draw a blur"}</button>
          <button className="btn sm" onClick={async () => {
            const c = v1 ? clipAt(v1, playhead) : null;
            if (!c) return toast("Move the playhead over a video clip", true);
            try {
              const r = await post<{ faces: { x: number; y: number; w: number; h: number }[] }>(`/api/projects/${projectId}/blur/faces`,
                { media_id: c.media_id, time: sourceTimeAt(c, playhead), scale: c.transform?.scale ?? 1, x: c.transform?.x ?? 0, y: c.transform?.y ?? 0 });
              if (!r.faces.length) return toast("No faces found in this frame", true);
              let tl = timeline, last = "";
              for (const f of r.faces) {                       // an oval fits a face best
                const x = addBlur(tl, playhead, f);
                if (!x.timeline || !x.id) continue;
                const y = updateBlur(x.timeline, x.id, { shape: "ellipse" });
                tl = y.timeline ?? x.timeline; last = x.id;
              }
              commit({ timeline: tl }, `Blur ${r.faces.length} face${r.faces.length === 1 ? "" : "s"}`);
              setSel(last);
              toast(`Blurred ${r.faces.length} face${r.faces.length === 1 ? "" : "s"} — press Follow it if they move`);
            } catch (e: any) { toast(e.message, true); }
          }}><Icon name="eyeoff" size={13} />Blur faces here</button>
        </div>
      </div>

      {blurs.length > 0 && (
        <div style={{ display: "grid", gap: 4 }}>
          {blurs.map((b) => (
            <div key={b.id} className={"row title-row" + (b.id === sel ? " on" : "")} style={{ fontSize: 12, gap: 6, cursor: "pointer" }}
              onClick={() => { setSel(b.id); seek(b.start + Math.min(0.5, b.duration / 2)); }}>
              <span className="mono">{fmtTime(b.start)}</span>
              <span>{{ blur: "Blur", pixelate: "Pixelate", black: "Black box" }[b.mode]}</span>
              <span className="dim grow">{b.duration.toFixed(1)} s{b.keys.length > 1 ? " · follows" : ""}</span>
              <button className="btn xs ghost" aria-label="Delete blur" onClick={(e) => { e.stopPropagation(); commit(removeBlur(timeline, b.id), "Delete blur"); if (sel === b.id) setSel(null); }}><Icon name="trash" size={12} /></button>
            </div>
          ))}
        </div>
      )}

      {cur && (
        <div className="insp-section">
          <h3 style={{ margin: 0 }}>Edit blur</h3>
          <div className="row" style={{ gap: 4 }}>
            {(["blur", "pixelate", "black"] as const).map((m) => (
              <button key={m} className={"btn xs" + (cur.mode === m ? " on" : " ghost")} onClick={() => set({ mode: m }, "Blur style")}>{{ blur: "Blur", pixelate: "Pixelate", black: "Black box" }[m]}</button>
            ))}
            <span className="spacer" />
            {(["rect", "ellipse"] as const).map((sh) => (
              <button key={sh} className={"btn xs" + (cur.shape === sh ? " on" : " ghost")} onClick={() => set({ shape: sh }, "Blur shape")}>{sh === "rect" ? "Box" : "Oval"}</button>
            ))}
          </div>
          {cur.mode !== "black" && <label className="field">Strength <span className="dim">{Math.round(cur.strength * 100)}%</span>
            <input type="range" min={0.1} max={1} step={0.05} value={cur.strength} onChange={(e) => set({ strength: +e.target.value }, "Blur strength")} /></label>}
          <div className="insp-grid">
            <label className="field">Starts at <span className="dim">{fmtTime(cur.start)}</span>
              <button className="btn xs" onClick={() => set({ start: playhead }, "Move blur")}>Move to playhead</button></label>
            <label className="field">Length (s)<input type="number" min={0.1} step={0.5} value={cur.duration} aria-label="Blur length"
              onChange={(e) => Number.isFinite(+e.target.value) && set({ duration: +e.target.value }, "Blur length")} /></label>
          </div>
          <button className="btn xs" onClick={() => playhead > cur.start && set({ duration: playhead - cur.start }, "Blur length")}>End it at the playhead</button>
          <div className="row" style={{ gap: 4, flexWrap: "wrap" }}>
            <button className="btn sm" disabled={!!trackJob} onClick={() => track(cur)}><Icon name="wand" size={13} />{cur.keys.length > 1 ? "Follow it again" : "Follow it"}</button>
            <button className="btn xs ghost" onClick={() => startDraw((box) => set({ keys: [{ t: cur.start, ...box }] }, "Redraw blur"))}>Redraw</button>
            {cur.keys.length > 1 && <button className="btn xs ghost" onClick={() => set({ keys: [cur.keys[0]] }, "Stop following")}>Keep it still</button>}
          </div>
          {tj && (tj.status === "running" || tj.status === "queued" || tj.status === "failed") && <JobRow job={tj} onChange={onJobs} />}
          <div className="muted" style={{ fontSize: 11 }}>Follow it works best on things with clear detail (a face, a sign). Check the preview; Redraw if it drifted.</div>
        </div>
      )}
    </div>
  );
}
