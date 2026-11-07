import React, { useState } from "react";
import { api, fmtTime } from "../api";
import { applyLayout, freezeSource, insertFreeze, RAMP_SLOWMO, RAMP_SPEEDUP, REVERSE_MAX, speedRamp, useReversed, type Corner, type Layout } from "../timeline/pro";
import { clipEnd, findClip, type ClipPatch, type OpResult } from "../timeline/ops";
import type { MediaAsset, MediaMap, Timeline } from "../timeline/types";
import { Icon, useToast } from "./ui";

/** Clip tab extras (Phase 15): freeze frame, reverse, speed ramps, layouts, green screen. */
export default function ProTools({ projectId, timeline, media, selection, playhead, W, H, commit, onPatch, onMediaAdded }: {
  projectId: string; timeline: Timeline; media: MediaMap; selection: string[]; playhead: number; W: number; H: number;
  commit: (r: OpResult, label: string, coalesce?: boolean) => boolean;
  onPatch: (id: string, p: ClipPatch, label: string) => void;
  onMediaAdded: () => Promise<void> | void;
}) {
  const toast = useToast();
  const [busy, setBusy] = useState<string | null>(null);
  const [hold, setHold] = useState(2);
  const [slow, setSlow] = useState(RAMP_SLOWMO.target);
  const [fast, setFast] = useState(RAMP_SPEEDUP.target);
  const [corner, setCorner] = useState<Corner>("br");
  const [pip, setPip] = useState(0.3);
  const ref = selection.length === 1 ? findClip(timeline, selection[0]) : null;
  const clip = ref?.track.kind === "video" ? ref.clip : null;
  const src = freezeSource(timeline, playhead, selection);
  const derive = async (mid: string, body: object) => {
    const r = await fetch(`/api/projects/${projectId}/media/${mid}/derive`, { method: "POST", headers: { "X-RJClip": "1", "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const d = await r.json();
    if (!r.ok) throw new Error(d.error ?? "failed");
    await onMediaAdded();
    return d.media as MediaAsset;
  };

  const freeze = async () => {
    if (!src) return toast("Put the playhead on a video clip", true);
    setBusy("freeze");
    try {
      const m = await derive(src.clip.media_id, { kind: "freeze", t: src.sourceT, seconds: hold });
      if (commit(insertFreeze(timeline, src.clip.id, playhead, m), "Freeze frame")) toast(`Froze ${fmtTime(playhead)} for ${hold} s`);
    } catch (e: any) { toast(`Couldn't freeze: ${e.message}`, true); }
    finally { setBusy(null); }
  };
  const reverse = async () => {
    if (!clip) return;
    setBusy("reverse");
    try {
      const m = await derive(clip.media_id, { kind: "reverse", start: clip.source_in, end: clip.source_out });
      if (commit(useReversed(timeline, clip.id, m), "Reverse clip")) toast("Reversed (this clip now plays backwards)");
    } catch (e: any) { toast(`Couldn't reverse: ${e.message}`, true); }
    finally { setBusy(null); }
  };
  const span = clip ? clip.source_out - clip.source_in : 0;
  const onClip = clip && playhead >= clip.start && playhead < clipEnd(clip);
  const layout = (l: Layout) => commit(applyLayout(timeline, playhead, W, H, l, corner, pip), l === "reset" ? "Reset layout" : "Layout");
  const ck = clip?.chroma ?? null;

  return (
    <div className="pro-tools" style={{ display: "grid", gap: 12, gridTemplateColumns: "minmax(0, 1fr)", minWidth: 0 }} data-testid="pro-tools">
      <div className="insp-section" style={{ marginBottom: 0, display: "grid", gap: 6 }}>
        <h3 style={{ margin: 0 }}>Freeze &amp; reverse</h3>
        <div className="row" style={{ gap: 6 }}>
          <button className="btn sm" disabled={!src || busy !== null} onClick={freeze} title="Hold the picture at the playhead; the sound pauses">
            <Icon name="pause" size={13} />{busy === "freeze" ? "Freezing…" : "Freeze frame"}</button>
          <label className="row" style={{ gap: 4, fontSize: 12 }}>for
            <input type="number" aria-label="Freeze seconds" min={0.5} max={10} step={0.5} value={hold} style={{ width: 52 }}
              onChange={(e) => setHold(Math.min(10, Math.max(0.5, +e.target.value || 2)))} /> s</label>
        </div>
        <button className="btn sm" disabled={!clip || span > REVERSE_MAX || busy !== null} onClick={reverse}
          title={span > REVERSE_MAX ? `Clips up to ${REVERSE_MAX} s can be reversed; split it first` : "Play this clip backwards (picture and sound)"}>
          <Icon name="undo" size={13} />{busy === "reverse" ? "Reversing…" : !clip ? "Reverse (select a video clip)" : `Reverse this clip (${span.toFixed(1)} s)`}</button>
      </div>

      <div className="insp-section" style={{ marginBottom: 0, display: "grid", gap: 6 }}>
        <h3 style={{ margin: 0 }}>Speed ramp</h3>
        <div className="dim" style={{ fontSize: 11 }}>Smoothly slows down (or speeds up) from the playhead, then back. Select a clip first.</div>
        <div className="row" style={{ gap: 6 }}>
          <button className="btn sm" disabled={!onClip} style={{ minWidth: 0 }}
            onClick={() => commit(speedRamp(timeline, clip!.id, playhead, { ...RAMP_SLOWMO, target: slow }), "Slow-mo ramp")}>Slow-mo</button>
          <input type="range" aria-label="Slow-mo speed" min={0.25} max={0.75} step={0.05} value={slow} style={{ flex: 1, minWidth: 0 }} onChange={(e) => setSlow(+e.target.value)} />
          <span className="mono dim" style={{ fontSize: 11, width: 36 }}>{slow.toFixed(2)}×</span>
        </div>
        <div className="row" style={{ gap: 6 }}>
          <button className="btn sm" disabled={!onClip} style={{ minWidth: 0 }}
            onClick={() => commit(speedRamp(timeline, clip!.id, playhead, { ...RAMP_SPEEDUP, target: fast }), "Speed-up ramp")}>Speed-up</button>
          <input type="range" aria-label="Speed-up speed" min={1.5} max={4} step={0.25} value={fast} style={{ flex: 1, minWidth: 0 }} onChange={(e) => setFast(+e.target.value)} />
          <span className="mono dim" style={{ fontSize: 11, width: 36 }}>{fast.toFixed(2)}×</span>
        </div>
      </div>

      <div className="insp-section" style={{ marginBottom: 0, display: "grid", gap: 6 }}>
        <h3 style={{ margin: 0 }}>Layout</h3>
        <div className="dim" style={{ fontSize: 11 }}>For two clips at the playhead (one on V2 above V1): your gameplay and a reaction, two angles…</div>
        <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) minmax(0,1fr)", gap: 4 }}>
          <button className="btn sm" onClick={() => layout("side_by_side")}>Side by side</button>
          <button className="btn sm" onClick={() => layout("top_bottom")}>Top / bottom</button>
          <button className="btn sm" onClick={() => layout("pip")}>Picture-in-picture</button>
          <button className="btn sm ghost" onClick={() => layout("reset")}>Reset</button>
        </div>
        <div className="row" style={{ gap: 6 }}>
          <select aria-label="Picture-in-picture corner" value={corner} onChange={(e) => setCorner(e.target.value as Corner)}>
            <option value="tl">Top left</option><option value="tr">Top right</option><option value="bl">Bottom left</option><option value="br">Bottom right</option>
          </select>
          <input type="range" aria-label="Picture-in-picture size" min={0.15} max={0.5} step={0.05} value={pip} style={{ flex: 1, minWidth: 0 }} onChange={(e) => setPip(+e.target.value)} />
          <span className="mono dim" style={{ fontSize: 11 }}>{Math.round(pip * 100)}%</span>
        </div>
      </div>

      <div className="insp-section" style={{ marginBottom: 0, display: "grid", gap: 6 }}>
        <div className="row"><h3 style={{ margin: 0 }}>Green screen</h3><span className="spacer" />
          <label className="row" style={{ gap: 4, fontSize: 12 }}>
            <input type="checkbox" aria-label="Green screen" disabled={!clip} checked={!!ck}
              onChange={(e) => clip && onPatch(clip.id, { chroma: e.target.checked ? { color: "#00ff00", similarity: 0.3, blend: 0.08 } : null }, "Green screen")} />On</label></div>
        <div className="dim" style={{ fontSize: 11 }}>Makes one colour see-through so the track below shows. Put the green-screen clip on V2 above your background.
          The preview is close; the export is exact.</div>
        {ck && clip && (
          <div className="insp-grid">
            <label className="field">Colour<input type="color" aria-label="Key colour" value={ck.color} onChange={(e) => onPatch(clip.id, { chroma: { ...ck, color: e.target.value } }, "Green screen")} /></label>
            <label className="field">Strength <span className="dim">{Math.round(ck.similarity * 100)}</span>
              <input type="range" aria-label="Key strength" min={0.05} max={0.6} step={0.01} value={ck.similarity} onChange={(e) => onPatch(clip.id, { chroma: { ...ck, similarity: +e.target.value } }, "Green screen")} /></label>
            <label className="field">Soft edge <span className="dim">{Math.round(ck.blend * 100)}</span>
              <input type="range" aria-label="Key soft edge" min={0} max={0.3} step={0.01} value={ck.blend} onChange={(e) => onPatch(clip.id, { chroma: { ...ck, blend: +e.target.value } }, "Green screen")} /></label>
          </div>
        )}
      </div>
    </div>
  );
}

export type { MediaMap };
