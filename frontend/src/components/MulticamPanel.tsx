import React, { useEffect, useState } from "react";
import { call, fmtTime, type Job } from "../api";
import { applyAutoColor, applyMulticam, angleOf, baseTrack, camLabel, removeMulticam, setClipAngle } from "../timeline/phase21";
import { findClip, type OpResult } from "../timeline/ops";
import type { ColorAdjust, MediaMap, Multicam, Timeline } from "../timeline/types";
import { JobRow, useToast } from "./ui";

interface Row { media_id: string; mic_media_id: string; label: string; offset?: string }

/** Editor → AI → Multicam (Phase 21): several cameras of the same moment. RJClip lines
 *  them up by sound and cuts to whoever is talking (or switches at a steady pace); you can
 *  change any shot by hand. */
export default function MulticamPanel({ projectId, timeline, media, selection, commit, jobs, onJobs, saved }: {
  projectId: string; timeline: Timeline; media: MediaMap; selection: string[];
  commit: (r: OpResult, label: string) => boolean; jobs: Job[]; onJobs: () => void; saved: boolean;
}) {
  const toast = useToast();
  const mc = timeline.multicam ?? null;
  const videos = Object.values(media).filter((m) => m.has_video);
  const sounds = Object.values(media).filter((m) => m.has_audio);
  const mainGuess = baseTrack(timeline)?.clips.find((c) => media[c.media_id]?.has_video)?.media_id ?? videos[0]?.id ?? "";
  const [rows, setRows] = useState<Row[]>(() => mc
    ? mc.angles.map((a) => ({ media_id: a.media_id, mic_media_id: a.mic_media_id ?? "", label: a.label ?? "" }))
    : [{ media_id: mainGuess, mic_media_id: "", label: "" }, { media_id: videos.find((m) => m.id !== mainGuess)?.id ?? "", mic_media_id: "", label: "" }]);
  const [mode, setMode] = useState<"speaker" | "pace">(mc?.mode ?? "speaker");
  const [wide, setWide] = useState<number | null>(mc?.wide ?? null);
  const [minShot, setMinShot] = useState(mc?.min_shot ?? 2);
  const [pace, setPace] = useState(mc?.pace ?? 5);
  const [jobId, setJobId] = useState<string | null>(null);
  const [share, setShare] = useState<number[] | null>(null);
  const [lowConf, setLowConf] = useState<string[]>([]);
  const [matching, setMatching] = useState(false);
  const matchColours = async () => {
    if (!mc) return;
    setMatching(true);
    try {
      const r = await call<{ results: Record<string, { color: ColorAdjust; changed: boolean }> }>("POST", `/api/projects/${projectId}/color/auto`,
        { media_ids: mc.angles.slice(1).map((a) => a.media_id), mode: "match", reference_media_id: mc.main_media_id });
      const got = Object.fromEntries(Object.entries(r.results).filter(([, v]) => v.changed).map(([k, v]) => [k, v.color]));
      if (!Object.keys(got).length) { toast("The cameras already match."); return; }
      if (commit(applyAutoColor(timeline, got), "Match camera colours")) toast(`Matched ${Object.keys(got).length} camera${Object.keys(got).length === 1 ? "" : "s"} to Cam 1`);
    } catch (e: any) { toast(e.message, true); }
    finally { setMatching(false); }
  };

  const job = jobs.find((j) => j.id === jobId);
  useEffect(() => {
    if (!job || job.status === "queued" || job.status === "running") return;
    setJobId(null);
    if (job.status !== "succeeded") return;                       // the job row shows the error
    type Got = Multicam["angles"][number] & { confidence: number; mic_confidence: number };
    const r = job.result as Omit<Multicam, "angles"> & { share: number[]; angles: Got[] };
    const plan: Multicam = {
      main_media_id: r.main_media_id, mode: r.mode, wide: r.wide ?? null, min_shot: r.min_shot, pace: r.pace,
      angles: r.angles.map((a, i) => ({ media_id: a.media_id, offset: a.offset, mic_media_id: a.mic_media_id || null,
        mic_offset: a.mic_offset, label: rows[i]?.label.trim().slice(0, 40) ?? "" })),
      switches: r.switches,
    };
    const res = applyMulticam(timeline, plan, media) as OpResult & { switched?: number };
    if (res.error) { toast(res.error, true); return; }
    if (commit(res, "Multicam")) {
      setShare(r.share);
      setLowConf(r.angles.flatMap((a, i) => [...(a.confidence < 0.5 ? [`camera ${i + 1}`] : []),
        ...(a.mic_media_id && a.mic_confidence < 0.5 ? [`mic ${i + 1}`] : [])]));
      toast(`Multicam: ${r.switches.length} shot${r.switches.length === 1 ? "" : "s"}`);
    }
  }, [job?.status]);
  const running = jobs.find((j) => j.kind === "multicam" && (j.status === "queued" || j.status === "running" || (j.id === jobId && j.status === "failed")));

  const set = (i: number, patch: Partial<Row>) => setRows(rows.map((r, k) => (k === i ? { ...r, ...patch } : r)));
  const run = async () => {
    try {
      const j = await call<Job>("POST", `/api/projects/${projectId}/multicam`, {
        angles: rows.map((r, i) => ({ media_id: r.media_id, mic_media_id: mode === "speaker" && r.mic_media_id ? r.mic_media_id : null,
          ...(i > 0 && r.offset?.trim() && Number.isFinite(+r.offset) ? { offset: +r.offset } : {}) })),
        mode, wide: mode === "speaker" ? wide : null, min_shot: minShot, pace,
      });
      setJobId(j.id); setShare(null); onJobs();
    } catch (e: any) { toast(e.message, true); }
  };
  const ids = rows.map((r) => r.media_id);
  const ready = rows.length >= 2 && ids.every(Boolean) && new Set(ids).size === ids.length;

  // the selected shot (pick its camera by hand)
  const ref = selection.length === 1 ? findClip(timeline, selection[0]) : undefined;
  const selAngle = mc && ref && ref.track.id === baseTrack(timeline)?.id ? angleOf(mc, ref.clip) : -1;

  return (
    <div className="insp-section" style={{ marginBottom: 0, display: "grid", gap: 6 }} data-testid="multicam">
      <h3 style={{ margin: 0 }}>Multicam</h3>
      <div className="dim" style={{ fontSize: 11 }}>Filmed with more than one camera (a podcast, an interview, a game + your face)? RJClip lines them up by their sound and cuts between them on your edit. Your cuts stay; the sound stays the main recording's.</div>
      {rows.map((r, i) => (
        <div key={i} style={{ display: "grid", gap: 3, gridTemplateColumns: "minmax(0, 1fr)" }} data-testid="multicam-row">
          <div className="row" style={{ gap: 6, minWidth: 0 }}>
            <strong style={{ fontSize: 12, flex: "none" }}>Cam {i + 1}{i === 0 ? " (main)" : ""}</strong>
            <select aria-label={`Camera ${i + 1}`} value={r.media_id} style={{ flex: 1, minWidth: 0 }} onChange={(e) => set(i, { media_id: e.target.value })}>
              <option value="">—</option>
              {videos.map((m) => <option key={m.id} value={m.id}>{m.original_name}</option>)}
            </select>
            {i >= 1 && <input aria-label={`Offset of camera ${i + 1}`} placeholder="auto" value={r.offset ?? ""} style={{ width: 52, flex: "none" }}
              title="Seconds to add to the main camera's time to get this camera's (leave empty to line up by sound; needed for a camera without sound)"
              onChange={(e) => set(i, { offset: e.target.value })} />}
            {i >= 2 && <button className="btn xs ghost" aria-label={`Remove camera ${i + 1}`} onClick={() => { setRows(rows.filter((_, k) => k !== i)); if (wide !== null && wide >= i) setWide(null); }}>✕</button>}
          </div>
          <div className="row" style={{ gap: 6, minWidth: 0 }}>
            <input aria-label={`Name of camera ${i + 1}`} placeholder="Name (optional)" value={r.label} maxLength={40} style={{ flex: 1, minWidth: 0 }}
              onChange={(e) => set(i, { label: e.target.value })} />
            {mode === "speaker" && (
              <select aria-label={`Mic of camera ${i + 1}`} value={r.mic_media_id} style={{ flex: 1, minWidth: 0 }} title="This person's own mic, if they had one. Otherwise the camera's sound is used."
                onChange={(e) => set(i, { mic_media_id: e.target.value })}>
                <option value="">Mic: the camera's sound</option>
                {sounds.filter((m) => m.id !== r.media_id).map((m) => <option key={m.id} value={m.id}>Mic: {m.original_name}</option>)}
              </select>)}
          </div>
        </div>
      ))}
      {rows.length < 4 && <button className="btn xs ghost" style={{ justifySelf: "start" }} onClick={() => setRows([...rows, { media_id: "", mic_media_id: "", label: "" }])}>+ Add a camera</button>}
      <label className="field">Switch cameras
        <select aria-label="Multicam mode" value={mode} onChange={(e) => setMode(e.target.value as "speaker" | "pace")}>
          <option value="speaker">to whoever is talking</option>
          <option value="pace">at a steady pace (one person)</option>
        </select></label>
      {mode === "speaker" ? (<>
        <label className="field">Wide shot (people talking at once, long pauses)
          <select aria-label="Wide camera" value={wide ?? ""} onChange={(e) => setWide(e.target.value === "" ? null : +e.target.value)}>
            <option value="">none: stay on the last person</option>
            {rows.map((_, i) => <option key={i} value={i}>Cam {i + 1}</option>)}
          </select></label>
        <label className="field">Shortest shot: {minShot.toFixed(1)} s
          <input type="range" aria-label="Shortest shot" min={0.5} max={6} step={0.5} value={minShot} onChange={(e) => setMinShot(+e.target.value)} /></label>
      </>) : (
        <label className="field">About every {pace} s
          <input type="range" aria-label="Switch pace" min={2} max={15} step={1} value={pace} onChange={(e) => setPace(+e.target.value)} /></label>
      )}
      <div className="row" style={{ gap: 6, flexWrap: "wrap" }}>
        <button className="btn primary sm" disabled={!ready || !!running} onClick={run}>{mc ? "Redo the switching" : "Line up & switch"}</button>
        {mc && <button className="btn sm" disabled={matching || !saved} title="Makes every camera's brightness, contrast and white balance match Cam 1"
          onClick={matchColours}>{matching ? "Matching…" : "Match colours to Cam 1"}</button>}
        {mc && <button className="btn sm" onClick={() => { if (commit(removeMulticam(timeline, media), "Multicam off")) setShare(null); }}>Back to one camera</button>}
      </div>
      {running && <JobRow job={running} onChange={onJobs} />}
      {share && mc && <div className="dim" style={{ fontSize: 11 }} data-testid="multicam-share">
        {share.map((s, i) => `${camLabel(mc, i)} ${Math.round(s * 100)}%`).join(" · ")}</div>}
      {lowConf.length > 0 && <div className="chip warn" style={{ whiteSpace: "normal", height: "auto", lineHeight: 1.35, padding: "3px 8px", fontSize: 11, borderRadius: 8 }}>
        The sound didn't match clearly for {lowConf.join(", ")}: check that shot lines up (lips with voice). Click a camera's shots below to swap them by hand.</div>}
      {mc && (
        <div style={{ display: "grid", gap: 4 }} data-testid="multicam-pick">
          <span style={{ fontSize: 12 }}>{selAngle >= 0 ? `Selected shot at ${fmtTime(ref!.clip.start)} shows:` : "Select a shot on V1 to change its camera"}</span>
          {selAngle >= 0 && <div className="row" style={{ gap: 4, flexWrap: "wrap" }}>
            {mc.angles.map((_, i) => <button key={i} className={"btn xs" + (i === selAngle ? " primary" : "")} aria-pressed={i === selAngle}
              onClick={() => commit(setClipAngle(timeline, ref!.clip.id, i, media), "Change camera")}>{camLabel(mc, i)}</button>)}
          </div>}
        </div>)}
      {!saved && !mc && <div className="dim" style={{ fontSize: 11 }}>It uses the saved project; your latest change saves in a moment.</div>}
    </div>
  );
}
