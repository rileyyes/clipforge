import React, { useEffect, useState } from "react";
import { fmtTime } from "../api";
import { clipDuration, clipEnd, findClip, type ClipPatch } from "../timeline/ops";
import type { MediaMap, Timeline } from "../timeline/types";

/** Number field that commits on Enter/blur (so typing "1." doesn't fight the state). */
function Num({ label, value, onCommit, step = 0.01, min, max, suffix }: {
  label: string; value: number; onCommit: (v: number) => void; step?: number; min?: number; max?: number; suffix?: string;
}) {
  const [v, setV] = useState(String(value));
  useEffect(() => setV(String(Math.round(value * 1000) / 1000)), [value]);
  const commit = () => {
    const n = parseFloat(v);
    if (isFinite(n) && n !== value) onCommit(n); else setV(String(Math.round(value * 1000) / 1000));
  };
  return (
    <label className="field"><span>{label}{suffix && <span className="dim"> ({suffix})</span>}</span>
      <input type="number" step={step} min={min} max={max} value={v} onChange={(e) => setV(e.target.value)}
        onBlur={commit} onKeyDown={(e) => { if (e.key === "Enter") { commit(); (e.target as HTMLInputElement).blur(); } }} />
    </label>
  );
}

export default function Inspector({ timeline, media, selection, onPatch, onTrim, onMove }: {
  timeline: Timeline; media: MediaMap; selection: string[];
  onPatch: (id: string, p: ClipPatch, label: string) => void;
  onTrim: (id: string, edge: "start" | "end", t: number) => void;
  onMove: (id: string, start: number) => void;
}) {
  const ref = selection.length === 1 ? findClip(timeline, selection[0]) : null;
  if (!ref) {
    return (
      <div style={{ display: "contents" }}>
        <div className="pane-body muted" style={{ fontSize: 12 }}>
          {selection.length > 1 ? `${selection.length} clips selected.` : "Select a clip to see and edit its properties."}
          <div style={{ marginTop: 18, display: "grid", gap: 6 }}>
            <div className="dim">Shortcuts</div>
            {[["Space", "Play / pause"], ["S", "Split at playhead"], ["Del", "Delete"], ["Shift+Del", "Ripple delete"],
              ["Ctrl+D", "Duplicate"], ["Ctrl+Z / Ctrl+Shift+Z", "Undo / redo"], ["← →", "Step one frame"], ["N", "Toggle snapping"],
              ["Ctrl + wheel", "Zoom timeline"]].map(([k, d]) => (
              <div key={k} className="row"><span className="kbd">{k}</span><span>{d}</span></div>
            ))}
          </div>
        </div>
      </div>
    );
  }
  const { clip, track } = ref;
  const m = media[clip.media_id];
  return (
    <div style={{ display: "contents" }}>
      <div className="pane-body">
        <div className="row" style={{ marginBottom: 6 }}><strong style={{ fontSize: 12 }}>Clip</strong><span className={"chip " + (track.kind === "video" ? "run" : "ok")}>{track.name}</span></div>
        <div className="insp-section">
          <div className="ellipsis" style={{ fontWeight: 600 }} title={m?.original_name}>{m?.original_name ?? "missing media"}</div>
          <dl className="kv">
            <dt>On timeline</dt><dd className="mono">{fmtTime(clip.start)} → {fmtTime(clipEnd(clip))}</dd>
            <dt>Duration</dt><dd className="mono">{fmtTime(clipDuration(clip))}</dd>
            <dt>From source</dt><dd className="mono">{fmtTime(clip.source_in)} → {fmtTime(clip.source_out)}</dd>
            {clip.link_id && <><dt>Linked</dt><dd>edits move picture and sound together</dd></>}
          </dl>
          {track.locked && <span className="chip warn">Track is locked</span>}
        </div>

        <div className="insp-section">
          <h3 style={{ margin: 0 }}>Timing</h3>
          <div className="insp-grid">
            <Num label="Start" suffix="s" value={clip.start} min={0} onCommit={(v) => onMove(clip.id, v)} />
            <Num label="Speed" suffix="×" value={clip.speed} step={0.05} min={0.25} max={4}
              onCommit={(v) => onPatch(clip.id, { speed: v }, "Change speed")} />
            <Num label="Source in" suffix="s" value={clip.source_in} min={0}
              onCommit={(v) => onTrim(clip.id, "start", clip.start + (v - clip.source_in) / clip.speed)} />
            <Num label="Source out" suffix="s" value={clip.source_out} max={m?.duration}
              onCommit={(v) => onTrim(clip.id, "end", clipEnd(clip) + (v - clip.source_out) / clip.speed)} />
          </div>
        </div>

        {track.kind === "audio" && (
          <div className="insp-section">
            <h3 style={{ margin: 0 }}>Audio</h3>
            <label className="field">Volume <span className="mono" style={{ color: "var(--text)" }}>{Math.round(clip.volume * 100)}%</span>
              <input type="range" min={0} max={2} step={0.01} value={clip.volume}
                onChange={(e) => onPatch(clip.id, { volume: +e.target.value }, "Change volume")} />
            </label>
            <div className="dim" style={{ fontSize: 11 }}>Above 100% is applied on export; the preview caps at 100%.</div>
          </div>
        )}

        {track.kind === "video" && (
          <div className="insp-section">
            <h3 style={{ margin: 0 }}>Transform</h3>
            <label className="field">Scale <span className="mono" style={{ color: "var(--text)" }}>{Math.round(clip.transform.scale * 100)}%</span>
              <input type="range" min={0.1} max={3} step={0.01} value={clip.transform.scale}
                onChange={(e) => onPatch(clip.id, { transform: { scale: +e.target.value } }, "Scale")} />
            </label>
            <div className="insp-grid">
              <Num label="Position X" suffix="px" step={1} value={clip.transform.x} onCommit={(v) => onPatch(clip.id, { transform: { x: v } }, "Move picture")} />
              <Num label="Position Y" suffix="px" step={1} value={clip.transform.y} onCommit={(v) => onPatch(clip.id, { transform: { y: v } }, "Move picture")} />
            </div>
            <button className="btn sm" onClick={() => onPatch(clip.id, { transform: { x: 0, y: 0, scale: 1 } }, "Reset transform")}>Reset</button>
            <div className="dim" style={{ fontSize: 11 }}>Scale/position render on export (e.g. picture-in-picture on V2). The preview shows the clip unscaled.</div>
          </div>
        )}
      </div>
    </div>
  );
}
