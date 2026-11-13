import React, { useEffect, useState } from "react";
import { fmtTime, type Job } from "../api";
import { cutRanges, findClip, newId, round6, sortClips, withTracks, type OpResult } from "../timeline/ops";
import { insertTeaser } from "../timeline/pro";
import { keepOnly, type Moment } from "../timeline/phase18";
import { paceScore, punchIns, slowStretches, PACE_GAP, type Pace, type Stretch } from "../timeline/phase19";
import { addTitle } from "../timeline/ops";
import type { Effect } from "../timeline/types";
import { fontsApi } from "../fonts";
import { addMarker } from "../timeline/ops";
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
export default function SmartPanel({ projectId, timeline, playhead, seek, commit, jobs, onJobs, onMediaAdded, saved, effects = [], addEffects, onPacing }: {
  projectId: string; timeline: Timeline; playhead: number; seek: (t: number) => void;
  /** Phase 19 pacing checker: the effects (it counts zooms, pop-ups…) and a way to add punch-ins */
  effects?: Effect[]; addEffects?: (list: Effect[], label: string) => void;
  onPacing?: (slow: Stretch[] | null) => void;
  commit: (r: OpResult, label: string) => boolean; jobs: Job[]; onJobs: () => void;
  onMediaAdded: () => Promise<void> | void;
  /** true when the server has the latest edit (the checks read the saved project) */
  saved: boolean;
}) {
  const toast = useToast();
  const [pace, setPace] = useState<Pace | null>(null);   // null = the checker isn't on
  const [motion, setMotion] = useState<{ step: number; values: number[] } | null>(null);
  const slow = pace ? slowStretches(timeline, effects, pace, motion) : null;
  const slowKey = slow ? slow.map((x) => `${x.start}-${x.end}`).join(",") : "off";
  useEffect(() => { onPacing?.(slow); }, [slowKey]);
  useEffect(() => () => onPacing?.(null), []);
  const checkPacing = async (p: Pace) => {
    setPace(p);
    try {
      const r = await getJSON(`/api/projects/${projectId}/pacing/motion`);
      setMotion(r.motion ? { step: r.step, values: r.motion } : null);
    } catch { setMotion(null); }
  };
  const [moments, setMoments] = useState<Moment[] | null>(null);
  const [keep, setKeep] = useState<Set<number>>(new Set());
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
      <div className="insp-section" style={{ marginBottom: 0, display: "grid", gap: 6 }} data-testid="pacing">
        <h3 style={{ margin: 0 }}>Pacing checker</h3>
        <div className="dim" style={{ fontSize: 11 }}>Well-edited videos keep giving the eye something new: a cut, a zoom, B-roll, text. This finds stretches where nothing on screen changes for longer than your pace allows (shown in red on the ruler). It counts the changes your edit makes{motion ? ", plus movement in footage the Auto Editor has analysed" : ""}.</div>
        <div className="row" style={{ gap: 4, flexWrap: "wrap" }}>
          {(["fast", "lively", "relaxed"] as Pace[]).map((p) => (
            <button key={p} className={"btn sm" + (pace === p ? " on" : "")} onClick={() => checkPacing(p)}>
              {p[0].toUpperCase() + p.slice(1)} <span className="dim">· {PACE_GAP[p]} s</span></button>
          ))}
          {pace && <button className="btn sm ghost" onClick={() => { setPace(null); onPacing?.(null); }}>Hide</button>}
        </div>
        {slow && (slow.length === 0
          ? <div style={{ fontSize: 12, color: "#2bb38a" }} data-testid="pacing-ok">No still stretches longer than {PACE_GAP[pace!]} s — nice pacing.</div>
          : <>
            <div style={{ fontSize: 12 }} data-testid="pacing-result">Pace score <strong className="mono">{paceScore(timeline, slow)}</strong> · {slow.length} still stretch{slow.length === 1 ? "" : "es"}</div>
            {slow.slice(0, 30).map((x, i) => (
              <div key={i} className="row" style={{ gap: 6, fontSize: 12, flexWrap: "wrap" }} data-testid="slow-row">
                <button className="btn xs" onClick={() => seek(x.start)}>{fmtTime(x.start)}–{fmtTime(x.end)}</button>
                <span className="dim grow">{(x.end - x.start).toFixed(1)} s</span>
                <button className="btn xs" title="Zoom in a little partway through" onClick={() => {
                  const made = punchIns(timeline, x, pace!);
                  if (!made.length) return toast("No footage there to zoom", true);
                  addEffects?.(made, "Punch in");
                }}>Punch in</button>
                <button className="btn xs" title="Pop-up words in the middle" onClick={() => {
                  const r = addTitle(timeline, "pop_text", (x.start + x.end) / 2 - 1.2);
                  if (commit(r, "Pop-up words")) { toast("Pop-up words added — edit them in the Text tab"); seek((x.start + x.end) / 2); }
                }}>Text</button>
              </div>
            ))}
            <button className="btn sm primary" onClick={() => {
              const made = slow.flatMap((x) => punchIns(timeline, x, pace!));
              if (!made.length) return toast("No footage there to zoom", true);
              addEffects?.(made, "Punch in all");
              toast(`${made.length} punch-in${made.length === 1 ? "" : "s"} added`);
            }}>Punch in all of them</button>
          </>)}
      </div>
      <div className="insp-section" style={{ marginBottom: 0, display: "grid", gap: 6 }} data-testid="funny-moments">
        <h3 style={{ margin: 0 }}>Funny-moment finder</h3>
        <div className="dim" style={{ fontSize: 11 }}>For long sessions with friends: finds where people get much louder than their normal talking (laughing, yelling, screaming) — more people at once scores higher. Each moment starts a few seconds early so the set-up is included. It can't tell a laugh from a shout, so preview them.</div>
        <button className="btn sm" disabled={!!busy || !saved} onClick={async () => {
          setBusy("moments");
          try {
            const m = await fontsApi.moments(projectId);
            setMoments(m); setKeep(new Set(m.map((_, i) => i)));
            if (!m.length) toast("No loud reactions found (are there voices on the audio tracks?)", true);
          } catch (e: any) { toast(e.message, true); } finally { setBusy(null); }
        }}><Icon name="search" size={13} />{busy === "moments" ? "Listening…" : moments ? "Find again" : "Find funny moments"}</button>
        {moments && moments.length > 0 && <>
          {moments.map((m, i) => (
            <div key={i} className="row" style={{ gap: 6, fontSize: 12 }} data-testid="moment">
              <input type="checkbox" checked={keep.has(i)} aria-label={`Keep moment ${i + 1}`}
                onChange={(e) => setKeep((k) => { const n = new Set(k); if (e.target.checked) n.add(i); else n.delete(i); return n; })} />
              <button className="btn xs" onClick={() => seek(m.start)}>{fmtTime(m.start)}–{fmtTime(m.end)}</button>
              <span className="ellipsis grow">{m.people > 1 ? `${m.people} people` : "1 person"} reacting</span>
              <span className="mono" style={{ color: m.score >= 70 ? "#2bb38a" : m.score >= 40 ? "#ffb703" : "var(--muted)" }}>{m.score}</span>
            </div>
          ))}
          <div className="row" style={{ gap: 4, flexWrap: "wrap" }}>
            <button className="btn sm" onClick={() => {
              let tl = timeline, n = 0;
              for (const i of keep) { const r = addMarker(tl, moments[i].reaction, "#ff5a3c"); if (r.error === undefined) { tl = { ...r.timeline, markers: r.timeline.markers!.map((mk) => mk.id === r.id ? { ...mk, label: `Funny ${fmtTime(moments[i].reaction)}` } : mk) }; n++; } }
              if (n && commit({ timeline: tl }, "Mark funny moments")) toast(`${n} marker${n === 1 ? "" : "s"} added (Shift+← and Shift+→ jump between them)`);
            }} disabled={!keep.size}>Mark them</button>
            <button className="btn sm primary" disabled={!keep.size} onClick={() => {
              const ranges = [...keep].map((i) => [moments[i].start, moments[i].end] as [number, number]);
              if (!confirm(`Keep only these ${ranges.length} moment${ranges.length === 1 ? "" : "s"} and cut everything else? (Ctrl+Z undoes it.)`)) return;
              if (commit(keepOnly(timeline, ranges), "Keep only the funny moments")) { setMoments(null); seek(0); toast("Highlights cut — the moments are now back to back"); }
            }}>Keep only these</button>
          </div>
        </>}
      </div>
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
