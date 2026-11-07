import React, { useEffect, useState } from "react";
import { fmtTime, type Job } from "../api";
import { cutRanges, findClip, newId, round6, sortClips, withTracks, type OpResult } from "../timeline/ops";
import { insertTeaser } from "../timeline/pro";
import type { Clip, MediaAsset, Timeline } from "../timeline/types";
import { Icon, useToast } from "./ui";

const H = { "X-RJClip": "1", "Content-Type": "application/json" };
async function getJSON(url: string) { const r = await fetch(url); const d = await r.json(); if (!r.ok) throw new Error(d.error); return d; }
async function postJSON(url: string, body: object = {}) {
  const r = await fetch(url, { method: "POST", headers: H, body: JSON.stringify(body) }); const d = await r.json();
  if (!r.ok) throw new Error(d.error); return d;
}

interface Hook { score: number | null; verdict: string; tips: { id: string; text: string }[]; actions?: { id: string; label: string; cut?: [number, number]; range?: [number, number] }[]; window_s?: number }
interface Broll { t: number; duration: number; media_id: string; source_in: number; word: string; media_name: string }

/** Put a B-roll moment (picture only) on the first video track above V1 that's free there. */
export function placeBroll(tl: Timeline, s: Broll): OpResult {
  const vids = tl.tracks.filter((t) => t.kind === "video");
  const end = s.t + s.duration;
  const free = vids.slice(1).find((t) => !t.locked && !t.clips.some((c) => c.start < end - 1e-6 && c.start + (c.source_out - c.source_in) / c.speed > s.t + 1e-6));
  let base = tl, target = free?.id;
  if (!target) {
    if (tl.tracks.length >= 32) return { error: "Track limit reached" };
    const n = vids.length + 1;
    const t = { id: newId(), kind: "video" as const, name: `V${n}`, muted: false, hidden: false, locked: false, clips: [] };
    const lastVideo = tl.tracks.map((x) => x.kind).lastIndexOf("video");
    base = { ...tl, tracks: [...tl.tracks.slice(0, lastVideo + 1), t, ...tl.tracks.slice(lastVideo + 1)] };
    target = t.id;
  }
  const clip = { id: newId(), media_id: s.media_id, start: round6(s.t), source_in: round6(s.source_in), source_out: round6(s.source_in + s.duration),
    speed: 1, volume: 1, transform: { x: 0, y: 0, scale: 1, rotation: 0 }, link_id: null, label: `B-roll: ${s.word}`,
    fade_in: 0.15, fade_out: 0.15 } as Clip;
  return { timeline: withTracks(base, (t) => (t.id === target ? { ...t, clips: sortClips([...t.clips, clip]) } : t)), created: [clip.id] };
}

/** Editor → AI: hook checker, B-roll from your own recordings, offline voiceover. */
export default function SmartPanel({ projectId, timeline, playhead, seek, commit, jobs, onJobs, onMediaAdded, saved }: {
  projectId: string; timeline: Timeline; playhead: number; seek: (t: number) => void;
  commit: (r: OpResult, label: string) => boolean; jobs: Job[]; onJobs: () => void;
  onMediaAdded: () => Promise<void> | void;
  /** true when the server has the latest edit (the checks read the saved project) */
  saved: boolean;
}) {
  const toast = useToast();
  const [hook, setHook] = useState<Hook | null>(null);
  const [broll, setBroll] = useState<{ suggestions: Broll[]; note: string | null } | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [voice, setVoice] = useState<{ ready: boolean; speakers: string[]; credit: string; supported: boolean; job: string | null } | null>(null);
  const [text, setText] = useState("");
  const [speaker, setSpeaker] = useState("Voice 1");
  const [speed, setSpeed] = useState(1);
  const [voJob, setVoJob] = useState<string | null>(null);
  const loadVoice = () => getJSON("/api/voice").then(setVoice).catch(() => {});
  useEffect(() => { loadVoice(); }, []);
  // the voice download isn't tied to this project, so follow it here
  const [setupJob, setSetupJob] = useState<Job | null>(null);
  useEffect(() => {
    if (!voice?.job) return;
    const t = window.setInterval(async () => {
      try {
        const j: Job = await getJSON(`/api/jobs/${voice.job}`);
        setSetupJob(j);
        if (j.status !== "queued" && j.status !== "running") { window.clearInterval(t); loadVoice(); }
      } catch { /* try again */ }
    }, 1000);
    return () => window.clearInterval(t);
  }, [voice?.job]);
  const vj = jobs.find((j) => j.id === voJob);
  useEffect(() => {
    if (!vj || vj.status === "queued" || vj.status === "running") return;
    setVoJob(null);
    if (vj.status !== "succeeded") { toast(`Voiceover failed: ${vj.error}`, true); return; }
    const m = (vj.result as any).media as MediaAsset;
    (async () => {
      await onMediaAdded();
      // on the first audio track that's free at the playhead (not music), else a new "Voiceover" track
      const end = playhead + m.duration;
      const free = timeline.tracks.find((t) => t.kind === "audio" && t.role !== "music" && !t.locked
        && !t.clips.some((c) => c.start < end - 1e-6 && c.start + (c.source_out - c.source_in) / c.speed > playhead + 1e-6));
      let base = timeline, target = free?.id;
      if (!target) {
        const t = { id: newId(), kind: "audio" as const, name: "Voiceover", muted: false, hidden: false, locked: false, clips: [] };
        base = { ...timeline, tracks: [...timeline.tracks, t] }; target = t.id;
      }
      const clip = { id: newId(), media_id: m.id, start: round6(playhead), source_in: 0, source_out: round6(m.duration), speed: 1, volume: 1,
        transform: { x: 0, y: 0, scale: 1, rotation: 0 }, link_id: null, label: "Voiceover" } as Clip;
      if (commit({ timeline: withTracks(base, (t) => (t.id === target ? { ...t, clips: sortClips([...t.clips, clip]) } : t)) }, "Add voiceover"))
        toast(`Voiceover added at ${fmtTime(playhead)}`);
    })();
  }, [vj?.status]);

  const runHook = async () => {
    setBusy("hook");
    try { setHook(await getJSON(`/api/projects/${projectId}/hook`)); } catch (e: any) { toast(e.message, true); } finally { setBusy(null); }
  };
  const runBroll = async () => {
    setBusy("broll");
    try { setBroll(await getJSON(`/api/projects/${projectId}/broll/clips`)); } catch (e: any) { toast(e.message, true); } finally { setBusy(null); }
  };
  const action = (a: NonNullable<Hook["actions"]>[number]) => {
    const r = a.id === "trim_start" && a.cut ? cutRanges(timeline, [a.cut]) : a.range ? insertTeaser(timeline, a.range[0], a.range[1]) : { error: "?" };
    if (commit(r, a.id === "teaser" ? "Add teaser" : "Cut slow start")) { toast("Done — check the hook again to see the new score"); setHook(null); seek(0); }
  };
  const scoreColor = (s: number) => (s >= 75 ? "#2bb38a" : s >= 50 ? "#ffb703" : "#ff5a3c");

  return (
    <div className="pane-body" style={{ display: "grid", gap: 12, alignContent: "start", gridTemplateColumns: "minmax(0, 1fr)" }} data-testid="smart-panel">
      <div className="insp-section" style={{ marginBottom: 0, display: "grid", gap: 6 }}>
        <h3 style={{ margin: 0 }}>Hook checker</h3>
        <div className="dim" style={{ fontSize: 11 }}>How strong are your first seconds? Viewers decide fast. Measured from your edit: when you start talking, energy, movement, intro length and your first sentence.</div>
        <button className="btn sm" disabled={busy !== null || !saved} onClick={runHook} title={saved ? "" : "Wait for the save to finish"}>
          <Icon name="wand" size={13} />{busy === "hook" ? "Checking…" : "Check my hook"}</button>
        {hook && (
          <div data-testid="hook-result" style={{ display: "grid", gap: 6 }}>
            {hook.score !== null && (
              <div className="row" style={{ gap: 8 }}>
                <span className="hook-score" style={{ color: scoreColor(hook.score), borderColor: scoreColor(hook.score) }}>{hook.score}</span>
                <span style={{ fontSize: 12 }}>{hook.verdict}<span className="dim"> (first {hook.window_s} s)</span></span>
              </div>
            )}
            {hook.score === null && <div className="dim" style={{ fontSize: 12 }}>{hook.verdict}</div>}
            {hook.tips.map((t) => <div key={t.id} className="hook-tip">• {t.text}</div>)}
            {(hook.actions ?? []).map((a) => (
              <div key={a.id} className="row" style={{ gap: 6 }}>
                <button className="btn sm primary" onClick={() => action(a)}>{a.label}</button>
                {a.range && <button className="btn xs ghost" onClick={() => seek(a.range![0])}>Preview it</button>}
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="insp-section" style={{ marginBottom: 0, display: "grid", gap: 6 }}>
        <h3 style={{ margin: 0 }}>B-roll from your clips</h3>
        <div className="dim" style={{ fontSize: 11 }}>When you mention something, show the moment from your other recordings where it comes up (put on V2, picture only). Transcribe all your recordings first.</div>
        <button className="btn sm" disabled={busy !== null || !saved} onClick={runBroll}><Icon name="search" size={13} />{busy === "broll" ? "Looking…" : "Find B-roll"}</button>
        {broll?.note && <div className="dim" style={{ fontSize: 12 }}>{broll.note}</div>}
        {broll && broll.suggestions.length > 0 && (<>
          {broll.suggestions.map((s, i) => (
            <div key={i} className="row broll-row" data-testid="broll-row">
              <button className="btn xs ghost mono" onClick={() => seek(s.t)}>{fmtTime(s.t)}</button>
              <span className="ellipsis grow" style={{ fontSize: 12 }} title={`${s.media_name} at ${fmtTime(s.source_in)}`}>“{s.word}” → {s.media_name}</span>
              <button className="btn xs" onClick={() => { if (commit(placeBroll(timeline, s), "Add B-roll")) setBroll({ ...broll, suggestions: broll.suggestions.filter((x) => x !== s) }); }}>Add</button>
            </div>
          ))}
          <button className="btn sm" onClick={() => {
            let tl = timeline; let n = 0;
            for (const s of broll.suggestions) { const r = placeBroll(tl, s); if (r.timeline) { tl = r.timeline; n++; } }
            if (commit({ timeline: tl }, "Add B-roll")) { toast(`Added ${n} B-roll clip${n === 1 ? "" : "s"}`); setBroll({ ...broll, suggestions: [] }); }
          }}>Add all</button>
        </>)}
      </div>

      <div className="insp-section" style={{ marginBottom: 0, display: "grid", gap: 6 }}>
        <h3 style={{ margin: 0 }}>Voiceover</h3>
        {!voice ? <span className="dim">Loading…</span> : !voice.ready ? (<>
          <div className="dim" style={{ fontSize: 11 }}>Type a line and a free voice reads it, on your computer (no internet after a one-time ~95 MB download).</div>
          <button className="btn sm" disabled={!voice.supported || (!!voice.job && setupJob?.status !== "failed")}
            onClick={async () => { try { const r = await postJSON("/api/voice/setup"); setVoice({ ...voice, job: r.job_id }); onJobs(); } catch (e: any) { toast(e.message, true); } }}>
            <Icon name="download" size={13} />{setupJob && setupJob.status === "running" ? `Downloading… ${Math.round((setupJob.progress ?? 0) * 100)}%` : "Download the voice"}</button>
          {setupJob?.status === "failed" && <div className="err" style={{ fontSize: 12 }}>{setupJob.error}</div>}
        </>) : (<>
          <textarea aria-label="Voiceover text" rows={3} maxLength={2000} value={text} placeholder="What should the voice say?" onChange={(e) => setText(e.target.value)} />
          <div className="row" style={{ gap: 6 }}>
            <select aria-label="Voice" value={speaker} onChange={(e) => setSpeaker(e.target.value)}>{voice.speakers.map((s) => <option key={s}>{s}</option>)}</select>
            <label className="row" style={{ gap: 4, fontSize: 12, flex: 1, minWidth: 0 }}>Speed
              <input type="range" aria-label="Voice speed" min={0.7} max={1.4} step={0.05} value={speed} onChange={(e) => setSpeed(+e.target.value)} style={{ flex: 1, minWidth: 0 }} /></label>
          </div>
          <button className="btn sm primary" disabled={!text.trim() || !!voJob} onClick={async () => {
            try { const r = await postJSON(`/api/projects/${projectId}/voiceover`, { text, speaker, speed }); setVoJob(r.job_id); onJobs(); }
            catch (e: any) { toast(e.message, true); }
          }}><Icon name="mic" size={13} />{voJob ? "Speaking…" : `Add voiceover at ${fmtTime(playhead)}`}</button>
          <div className="dim" style={{ fontSize: 10 }}>{voice.credit} — put this in your video description.</div>
        </>)}
      </div>
    </div>
  );
}

export { findClip };
