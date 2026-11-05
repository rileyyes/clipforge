import React, { useEffect, useState } from "react";
import { ApiError, facecamApi, fmtTime, type Job } from "../api";
import { camAspect, defaultFaceCam, layoutBox } from "../timeline/facecam";
import { clipAt, sourceTimeAt } from "../timeline/ops";
import type { CamCorner, CamRange, FaceCam, MediaMap, OutputSettings, Project, Timeline } from "../timeline/types";
import { Icon, JobRow, useToast } from "./ui";

const CORNERS: [CamCorner, string][] = [["top_left", "↖ Top left"], ["top_right", "↗ Top right"], ["bottom_left", "↙ Bottom left"], ["bottom_right", "↘ Bottom right"]];
const NO_CROP = { left: 0, right: 0, top: 0, bottom: 0 };

/** Editor → Face cam: a webcam recording on top of the main one, following every cut. */
export default function FaceCamPanel({ projectId, project, timeline, media, output, facecam, setFacecam, playhead, seek, jobs, onJobs }: {
  projectId: string; project: Project; timeline: Timeline; media: MediaMap; output: OutputSettings;
  facecam: FaceCam | null; setFacecam: (fc: FaceCam | null, label: string) => void;
  playhead: number; seek: (t: number) => void; jobs: Job[]; onJobs: () => void;
}) {
  const toast = useToast();
  const videos = project.media.filter((m) => m.has_video);
  const v1 = timeline.tracks.find((t) => t.kind === "video" && !t.hidden);
  const mainGuess = v1?.clips[0]?.media_id ?? videos[0]?.id ?? "";
  const [main, setMain] = useState(mainGuess);
  const [cam, setCam] = useState(videos.find((m) => m.id !== mainGuess)?.id ?? "");
  const [syncJob, setSyncJob] = useState<string | null>(null);
  const [pending, setPending] = useState<{ kind: "hidden" | "full"; start: number } | null>(null);
  const [busy, setBusy] = useState("");

  // the sync job's result: apply when confident, otherwise ask
  const sj = jobs.find((j) => j.id === syncJob);
  const [syncResult, setSyncResult] = useState<{ offset: number; confidence: number } | null>(null);
  useEffect(() => {
    if (!sj || sj.status !== "succeeded" || !facecam) return;
    const r = sj.result as { offset: number; confidence: number };
    setSyncJob(null);
    setSyncResult(r);
    if (r.confidence >= 0.5) {
      setFacecam({ ...facecam, offset: r.offset }, "Line up face cam");
      toast(`Lined up by sound: face cam ${describe(r.offset)}`);
    }
  }, [sj?.status]);

  if (!facecam) {
    const can = videos.length >= 2;
    return (
      <div className="pane-body">
        <div className="insp-section">
          <h3 style={{ margin: 0 }}>Face cam</h3>
          <p className="muted" style={{ fontSize: 12, margin: 0 }}>
            Put your webcam recording in a corner of the video. It follows every cut of the main recording,
            including the AI's, so it always stays in sync.
          </p>
          {!can ? (
            <div className="muted" style={{ fontSize: 12 }}>Import your face cam video first (Media → Import), next to your main recording.</div>
          ) : (<>
            <label className="field">Main recording (game / screen)
              <select value={main} onChange={(e) => { setMain(e.target.value); if (e.target.value === cam) setCam(""); }}>
                {videos.map((m) => <option key={m.id} value={m.id}>{m.original_name}</option>)}
              </select></label>
            <label className="field">Face cam video
              <select value={cam} onChange={(e) => setCam(e.target.value)} aria-label="Face cam video">
                <option value="">Choose…</option>
                {videos.filter((m) => m.id !== main).map((m) => <option key={m.id} value={m.id}>{m.original_name}</option>)}
              </select></label>
            <button className="btn primary sm" disabled={!cam || !main} onClick={async () => {
              const fc = defaultFaceCam(cam, main);
              setFacecam(fc, "Add face cam");
              if (media[cam]?.has_audio && media[main]?.has_audio) {
                try { const j = await facecamApi.sync(projectId, cam, main); setSyncJob(j.id); onJobs(); }
                catch (e: any) { toast(e.message, true); }
              }
            }}><Icon name="webcam" size={14} />Add face cam</button>
            <div className="muted" style={{ fontSize: 11 }}>If both have sound, ClipForge lines them up by matching it.</div>
          </>)}
        </div>
      </div>
    );
  }

  const fc = facecam;
  const set = (patch: Partial<FaceCam>, label: string) => setFacecam({ ...fc, ...patch }, label);
  const camAsset = media[fc.media_id], mainAsset = media[fc.main_media_id];
  const fps = output.fps || 30;
  const box = layoutBox(fc, output.width, output.height, camAspect(fc, camAsset));
  const matteReady = (project.mattes ?? []).includes(fc.media_id);
  const matteJob = jobs.find((j) => j.kind === "facecam_matte" && (j.params as any)?.media_id === fc.media_id && (j.status === "running" || j.status === "queued" || j.status === "failed"));
  const syncing = jobs.find((j) => j.kind === "facecam_sync" && (j.status === "running" || j.status === "queued" || (j.id === syncJob && j.status === "failed")));

  // main-recording time under the playhead (ranges are stored in it, so they follow cuts)
  const clip = v1 ? clipAt(v1, playhead) : null;
  const mainNow = clip && clip.media_id === fc.main_media_id ? sourceTimeAt(clip, playhead) : null;
  const timelineOf = (mainT: number): number | null => {
    const c = v1?.clips.find((k) => k.media_id === fc.main_media_id && mainT >= k.source_in && mainT < k.source_out);
    return c ? c.start + (mainT - c.source_in) / c.speed : null;
  };
  const addRange = (kind: "hidden" | "full") => {
    if (mainNow === null) return toast("Move the playhead over the main recording first", true);
    if (!pending || pending.kind !== kind) { setPending({ kind, start: mainNow }); return; }
    const a = Math.min(pending.start, mainNow), b = Math.max(pending.start, mainNow);
    setPending(null);
    if (b - a < 0.05) return toast("Move the playhead to where it should end, then press again", true);
    set({ [kind]: [...fc[kind], { start: round3(a), end: round3(b) }] } as any, kind === "hidden" ? "Hide face cam" : "Face cam full screen");
  };
  const rangeList = (kind: "hidden" | "full") => fc[kind].map((r: CamRange, i: number) => {
    const t = timelineOf(r.start);
    return (
      <div key={i} className="row" style={{ fontSize: 12, gap: 6 }}>
        <span className="mono">{t === null ? "(cut out)" : fmtTime(t)}</span>
        <span className="dim">{(r.end - r.start).toFixed(1)} s</span>
        <span className="spacer" />
        {t !== null && <button className="btn xs ghost" onClick={() => seek(t)}>Go</button>}
        <button className="btn xs ghost" aria-label="Remove" onClick={() => set({ [kind]: fc[kind].filter((_, k) => k !== i) } as any, "Remove face cam range")}><Icon name="x" size={12} /></button>
      </div>
    );
  });

  return (
    <div className="pane-body" data-testid="facecam-panel">
      <div className="insp-section">
        <div className="row"><h3 style={{ margin: 0 }}>Face cam</h3><span className="spacer" />
          <label className="row" style={{ fontSize: 12 }}><input type="checkbox" checked={fc.enabled} onChange={(e) => set({ enabled: e.target.checked }, e.target.checked ? "Show face cam" : "Hide face cam")} />Show</label>
          <button className="btn xs ghost" onClick={() => setFacecam(null, "Remove face cam")}><Icon name="trash" size={12} />Remove</button>
        </div>
        <div className="muted" style={{ fontSize: 12 }}>{camAsset?.original_name} over {mainAsset?.original_name}</div>
      </div>

      <div className="insp-section">
        <h3 style={{ margin: 0 }}>Sync</h3>
        <div className="row" style={{ fontSize: 12 }}>The face cam is {describe(fc.offset)}.</div>
        {syncing && <JobRow job={syncing} onChange={onJobs} />}
        {syncResult && syncResult.confidence < 0.5 && (
          <div className="banner" style={{ fontSize: 12 }}>
            The sound didn't match clearly (maybe the face cam mic didn't hear the same thing). Best guess: {describe(syncResult.offset)}.
            <button className="btn xs" onClick={() => { set({ offset: syncResult.offset }, "Line up face cam"); setSyncResult(null); }}>Use it anyway</button>
          </div>
        )}
        <div className="row" style={{ flexWrap: "wrap", gap: 4 }}>
          <button className="btn sm" disabled={!!syncing || !camAsset?.has_audio || !mainAsset?.has_audio}
            title={camAsset?.has_audio && mainAsset?.has_audio ? "Match the sound of both recordings" : "Both recordings need sound for this"}
            onClick={async () => { try { setSyncResult(null); const j = await facecamApi.sync(projectId, fc.media_id, fc.main_media_id); setSyncJob(j.id); onJobs(); } catch (e: any) { toast(e.message, true); } }}>
            <Icon name="music" size={13} />Line up by sound</button>
          <button className="btn xs ghost" title="1 frame earlier" onClick={() => set({ offset: round3(fc.offset - 1 / fps) }, "Nudge face cam")}>−1 frame</button>
          <button className="btn xs ghost" title="1 frame later" onClick={() => set({ offset: round3(fc.offset + 1 / fps) }, "Nudge face cam")}>+1 frame</button>
          <label className="row" style={{ fontSize: 12 }}>Offset (s)
            <input type="number" step={0.01} value={fc.offset} style={{ width: 80 }} aria-label="Face cam offset"
              onChange={(e) => Number.isFinite(+e.target.value) && set({ offset: +e.target.value }, "Face cam offset")} /></label>
        </div>
      </div>

      <div className="insp-section">
        <h3 style={{ margin: 0 }}>Position</h3>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 4 }}>
          {CORNERS.map(([c, label]) => (
            <button key={c} className={"btn sm" + (fc.corner === c ? " on" : " ghost")} onClick={() => set({ corner: c }, "Face cam corner")}>{label}</button>
          ))}
        </div>
        <label className="field">Size <span className="dim">{Math.round(fc.size * 100)}% of the width</span>
          <input type="range" min={0.08} max={0.9} step={0.01} value={fc.size} aria-label="Face cam size"
            onChange={(e) => set({ size: +e.target.value, corner: fc.corner === "custom" ? "bottom_right" : fc.corner }, "Face cam size")} /></label>
        <label className="field">Gap to the edge <span className="dim">{Math.round(fc.margin * 100)}%</span>
          <input type="range" min={0} max={0.1} step={0.005} value={fc.margin} onChange={(e) => set({ margin: +e.target.value }, "Face cam gap")} /></label>
        <div className="dim" style={{ fontSize: 11 }}>{Math.round(box.w * output.width)}×{Math.round(box.h * output.height)} px</div>
      </div>

      <div className="insp-section">
        <h3 style={{ margin: 0 }}>Look</h3>
        <div className="row" style={{ gap: 4 }}>
          {(["rect", "rounded", "circle"] as const).map((s) => (
            <button key={s} className={"btn sm" + (fc.shape === s ? " on" : " ghost")} onClick={() => set({ shape: s }, "Face cam shape")}>
              {{ rect: "Square corners", rounded: "Rounded", circle: "Circle" }[s]}</button>
          ))}
        </div>
        <div className="row" style={{ gap: 4, flexWrap: "wrap" }}>
          <button className="btn sm" disabled={!!busy} onClick={async () => {
            setBusy("crop");
            try { const r = await facecamApi.faceCrop(projectId, fc.media_id, fc.shape); set({ crop: r.crop }, "Crop face cam to face"); toast(`Cropped around your face (seen in ${r.faces_seen} of ${r.samples} spots)`); }
            catch (e: any) { toast(e instanceof ApiError ? e.message : "Couldn't crop", true); }
            finally { setBusy(""); }
          }}><Icon name="scissors" size={13} />{busy === "crop" ? "Looking for your face…" : "Crop to my face"}</button>
          {(fc.crop.left || fc.crop.right || fc.crop.top || fc.crop.bottom) ? <button className="btn xs ghost" onClick={() => set({ crop: NO_CROP }, "Reset face cam crop")}>Reset crop</button> : null}
        </div>
        {!fc.remove_bg && (<>
          <label className="field">Border <span className="dim">{fc.border ? `${(fc.border * output.width).toFixed(0)} px` : "none"}</span>
            <div className="row"><input type="range" min={0} max={0.015} step={0.0005} value={fc.border} onChange={(e) => set({ border: +e.target.value }, "Face cam border")} />
              <input type="color" value={fc.border_color} aria-label="Border colour" onChange={(e) => set({ border_color: e.target.value }, "Face cam border colour")} /></div></label>
          <label className="row" style={{ fontSize: 12 }}><input type="checkbox" checked={fc.shadow} onChange={(e) => set({ shadow: e.target.checked }, "Face cam shadow")} />Soft shadow</label>
        </>)}
      </div>

      <div className="insp-section">
        <h3 style={{ margin: 0 }}>Background</h3>
        <label className="row" style={{ fontSize: 12 }}>
          <input type="checkbox" checked={fc.remove_bg} aria-label="Remove background" onChange={async (e) => {
            const on = e.target.checked;
            set({ remove_bg: on }, on ? "Remove face cam background" : "Keep face cam background");
            if (on && !matteReady) { try { await facecamApi.prepareCutout(projectId, fc.media_id); onJobs(); } catch (err: any) { toast(err.message, true); } }
          }} />Remove my background (AI, runs on this computer)</label>
        <div className="muted" style={{ fontSize: 11 }}>
          Shows just you over the video, no green screen needed. Works best with good light and a plain room;
          edges around hair can be rough. It's applied in the export (the preview shows the full picture).
          Turn it off any time.
        </div>
        {fc.remove_bg && (matteReady ? <div style={{ fontSize: 12 }}>✓ Ready for export</div>
          : matteJob ? <JobRow job={matteJob} onChange={onJobs} />
          : <button className="btn xs" onClick={async () => { try { await facecamApi.prepareCutout(projectId, fc.media_id); onJobs(); } catch (e: any) { toast(e.message, true); } }}>Prepare now</button>)}
      </div>

      <div className="insp-section">
        <h3 style={{ margin: 0 }}>Hide or fill the screen</h3>
        <div className="muted" style={{ fontSize: 11 }}>Press once where it starts, move the playhead, press again where it ends.</div>
        <div className="row" style={{ gap: 4, flexWrap: "wrap" }}>
          <button className={"btn sm" + (pending?.kind === "hidden" ? " on" : "")} onClick={() => addRange("hidden")}>
            <Icon name="eyeoff" size={13} />{pending?.kind === "hidden" ? "…hide until here" : "Hide from here"}</button>
          <button className={"btn sm" + (pending?.kind === "full" ? " on" : "")} onClick={() => addRange("full")}>
            <Icon name="fit" size={13} />{pending?.kind === "full" ? "…full screen until here" : "Full screen from here"}</button>
          {pending && <button className="btn xs ghost" onClick={() => setPending(null)}>Cancel</button>}
        </div>
        {fc.hidden.length > 0 && <div><div className="dim" style={{ fontSize: 11 }}>Hidden</div>{rangeList("hidden")}</div>}
        {fc.full.length > 0 && <div><div className="dim" style={{ fontSize: 11 }}>Full screen</div>{rangeList("full")}</div>}
        <button className="btn xs" disabled={!!busy} title="Uses the loud reactions found when the recording was analysed" onClick={async () => {
          setBusy("react");
          try {
            const res = await fetch(`/api/projects/${projectId}/fx/fun/suggest`, { method: "POST", headers: { "X-ClipForge": "1", "Content-Type": "application/json" }, body: JSON.stringify({ intensity: "minimal" }) });
            const data = await res.json();
            if (!res.ok) throw new Error(data.error || "Couldn't find reactions");
            const full = [...fc.full];
            for (const e of data.effects as { media_id: string; source_time: number; duration: number }[]) {
              if (e.media_id !== fc.main_media_id) continue;
              const r = { start: round3(Math.max(0, e.source_time - 0.3)), end: round3(e.source_time + Math.max(1.5, e.duration)) };
              if (!full.some((x) => x.start < r.end && r.start < x.end)) full.push(r);
            }
            const added = full.length - fc.full.length;
            if (added) set({ full }, "Face cam full screen on reactions");
            toast(added ? `Face cam fills the screen on ${added} big reaction${added === 1 ? "" : "s"}` : "No big reactions found in this edit");
          } catch (e: any) { toast(e.message, true); }
          finally { setBusy(""); }
        }}><Icon name="wand" size={12} />Full screen on my biggest reactions</button>
      </div>
    </div>
  );
}

function round3(v: number) { return Math.round(v * 1000) / 1000; }
/** cam time = main time + offset: a positive offset means the cam started recording first. */
function describe(offset: number) {
  if (Math.abs(offset) < 0.0005) return "lined up exactly (both started at the same moment)";
  return `shifted ${Math.abs(offset).toFixed(3)} s (it started recording ${offset > 0 ? "before" : "after"} the main recording)`;
}
