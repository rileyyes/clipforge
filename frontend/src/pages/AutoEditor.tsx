import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  api, autoedit, fmtTime, mediaUrl, uploadMedia, type AutoEditSettings, type Extras, type Beat, type Plan, type ProjectSummary,
} from "../api";
import { Icon, JobRow, useJobs, useToast } from "../components/ui";
import type { MediaAsset, Project } from "../timeline/types";
import { ACCEPT } from "./Dashboard";
import { go } from "../router";

const DEFAULTS: AutoEditSettings = {
  target_mode: "duration", target_seconds: 600, target_percent: 50, style: "balanced", silence: "balanced",
  keep_opening: true, context: true, include: [], exclude: [],
};

const STYLES: [AutoEditSettings["style"], string, string][] = [
  ["balanced", "Balanced", "A bit of everything"],
  ["excitement", "Excitement", "Loud, energetic, fast moments"],
  ["reactions", "Reactions", "Big reactions and loud spikes"],
  ["information", "Information", "Continuous explanation, little dead air"],
  ["action", "Visual action", "On-screen movement and scene changes"],
  ["humor", "Humor", "Best with a transcript"],
  ["story", "Storytelling", "Best with a transcript"],
];

const SILENCE: [AutoEditSettings["silence"], string][] = [
  ["off", "Off — keep all pauses"],
  ["conservative", "Conservative — only long dead air"],
  ["balanced", "Balanced — tighten pauses"],
  ["aggressive", "Aggressive — fast pacing"],
];

// ---------------------------------------------------------------- picker
function ProjectPicker() {
  const [projects, setProjects] = useState<ProjectSummary[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const toast = useToast();
  useEffect(() => { api.projects().then(setProjects).catch((e) => toast(e.message, true)); }, []);
  const importNew = async (file: File) => {
    try {
      const p = await api.createProject(file.name.replace(/\.[^.]+$/, "").slice(0, 100) || "Auto edit");
      setBusy(`Uploading ${file.name}…`);
      await uploadMedia(p.id, file, (f) => setBusy(`Uploading ${file.name} — ${Math.round(f * 100)}%`));
      go(`auto/${p.id}`);
    } catch (e: any) { toast(e.message, true); setBusy(null); }
  };
  return (
    <div className="page" style={{ maxWidth: 980 }}>
      <h1>AI Auto Editor</h1>
      <p className="muted">Turn a long raw recording into a tighter video. Choose a recording to start.</p>
      <div className="hero" style={{ gridTemplateColumns: "1fr 2fr" }}>
        <button className="action" disabled={!!busy} onClick={() => fileRef.current?.click()}>
          <Icon name="upload" /><strong>Import a recording</strong><span>{busy ?? "Creates a project for the edit"}</span>
        </button>
        <div className="card muted" style={{ fontSize: 12 }}>
          <strong style={{ color: "var(--text)" }}>How it works</strong>
          <ol style={{ margin: "6px 0 0", paddingLeft: 18, display: "grid", gap: 3 }}>
            <li>Analyse loudness, pauses, motion and scene cuts (runs on your computer).</li>
            <li>Pick a target length and style. Every moment is scored, with the reasons shown.</li>
            <li>Review: keep or drop any moment, play the rough cut.</li>
            <li>Send it to the Manual Editor as normal, editable clips. Nothing is changed in your original.</li>
          </ol>
        </div>
      </div>
      <input ref={fileRef} type="file" accept={ACCEPT} hidden onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) importNew(f); }} />
      <h2>Or use an existing project</h2>
      {projects === null ? <div className="muted">Loading…</div> : projects.filter((p) => p.media_count).length === 0 ? (
        <div className="empty">No projects with media yet.</div>
      ) : (
        <table className="list"><tbody>
          {projects.filter((p) => p.media_count && !p.error).map((p) => (
            <tr key={p.id}><td><strong>{p.name}</strong></td><td className="muted">{p.media_count} media</td>
              <td style={{ textAlign: "right" }}><button className="btn sm" onClick={() => go(`auto/${p.id}`)}>Choose</button></td></tr>
          ))}
        </tbody></table>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- source strip
function Strip({ plan, active, onPick }: { plan: Plan; active: number | null; onPick: (b: Beat) => void }) {
  const d = plan.source_duration || 1;
  return (
    <div style={{ position: "relative", height: 46, background: "var(--bg)", borderRadius: 6, border: "1px solid var(--line)", overflow: "hidden" }}
      title="Whole recording. Coloured blocks are kept moments (taller = higher score); grey were left out.">
      {plan.beats.map((b) => (
        <div key={b.id} onClick={() => onPick(b)} style={{
          position: "absolute", left: `${(b.start / d) * 100}%`, width: `max(2px, ${((b.end - b.start) / d) * 100}%)`,
          bottom: 0, height: `${20 + b.score * 0.8}%`, cursor: "pointer",
          background: b.selected ? "var(--accent)" : "var(--line-2)", opacity: active === b.id ? 1 : 0.85,
          outline: active === b.id ? "2px solid #fff" : "none",
        }} />
      ))}
    </div>
  );
}

// ---------------------------------------------------------------- main
function Workspace({ projectId }: { projectId: string }) {
  const [project, setProject] = useState<Project | null>(null);
  const [mediaId, setMediaId] = useState<string | null>(null);
  const [status, setStatus] = useState<{ media: { media_id: string; analyzed: boolean; has_transcript: boolean }[]; transcriber: string | null } | null>(null);
  const [settings, setSettings] = useState<AutoEditSettings>(DEFAULTS);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [planError, setPlanError] = useState<string | null>(null);
  const [planning, setPlanning] = useState(false);
  const [active, setActive] = useState<number | null>(null);
  const [applying, setApplying] = useState(false);
  const [filter, setFilter] = useState<"all" | "kept" | "dropped">("all");
  const [roughCut, setRoughCut] = useState(false);
  const [extras, setExtrasState] = useState<Extras>(() => {
    try { return { ...EXTRAS_DEFAULT, ...JSON.parse(localStorage.getItem("cf:autoExtras") || "{}") }; } catch { return EXTRAS_DEFAULT; }
  });
  const setExtras = (patch: Partial<Extras>) => setExtrasState((x) => {
    const n = { ...x, ...patch };
    try { localStorage.setItem("cf:autoExtras", JSON.stringify(n)); } catch { /* storage unavailable */ }
    return n;
  });
  const videoRef = useRef<HTMLVideoElement>(null);
  const stopAt = useRef<number | null>(null);
  const { jobs, refresh } = useJobs(projectId);
  const toast = useToast();

  const loadStatus = () => autoedit.status(projectId).then(setStatus).catch((e) => toast(e.message, true));
  useEffect(() => {
    api.project(projectId).then((p) => {
      setProject(p);
      const first = p.media.find((m) => m.has_video) ?? p.media[0];
      if (first) setMediaId(first.id);
    }).catch((e) => toast(e.message, true));
    loadStatus();
  }, [projectId]);

  const media: MediaAsset | undefined = project?.media.find((m) => m.id === mediaId);
  const analyzed = !!status?.media.find((m) => m.media_id === mediaId)?.analyzed;
  const hasTranscript = !!status?.media.find((m) => m.media_id === mediaId)?.has_transcript;
  const job = jobs.find((j) => j.kind === "analyze" && j.params.media_id === mediaId);
  const jobActive = job && (job.status === "queued" || job.status === "running");
  useEffect(() => { if (job?.status === "succeeded") loadStatus(); }, [job?.status]);

  // sensible default target when media changes: ~25% of the source, min 1 min
  useEffect(() => {
    if (!media) return;
    setSettings((s) => ({ ...s, include: [], exclude: [], target_seconds: Math.max(60, Math.round(media.duration * 0.25 / 30) * 30) }));
    setPlan(null);
  }, [mediaId]);

  // recompute the plan whenever settings change (debounced)
  useEffect(() => {
    if (!analyzed || !mediaId) return;
    setPlanning(true);
    const t = setTimeout(() => {
      autoedit.plan(projectId, mediaId, settings)
        .then((p) => { setPlan(p); setPlanError(null); })
        .catch((e) => setPlanError(e.message))
        .finally(() => setPlanning(false));
    }, 250);
    return () => clearTimeout(t);
  }, [analyzed, mediaId, settings]);

  const set = (patch: Partial<AutoEditSettings>) => setSettings((s) => ({ ...s, ...patch }));
  const overrideOf = (id: number) => (settings.include.includes(id) ? "keep" : settings.exclude.includes(id) ? "drop" : "auto");
  const setOverride = (id: number, v: "auto" | "keep" | "drop") => set({
    include: v === "keep" ? [...settings.include.filter((x) => x !== id), id] : settings.include.filter((x) => x !== id),
    exclude: v === "drop" ? [...settings.exclude.filter((x) => x !== id), id] : settings.exclude.filter((x) => x !== id),
  });

  // ---- preview: a single moment, or the whole rough cut in order
  const playRange = (a: number, b: number) => {
    const v = videoRef.current;
    if (!v) return;
    setRoughCut(false);
    stopAt.current = b;
    v.currentTime = a;
    v.play().catch(() => {});
  };
  const onTime = () => {
    const v = videoRef.current;
    if (!v) return;
    if (roughCut && plan) {
      const segs = plan.segments;
      const cur = segs.findIndex((s) => v.currentTime >= s.source_in - 0.05 && v.currentTime < s.source_out);
      if (cur === -1) {
        const next = segs.find((s) => s.source_in > v.currentTime);
        if (next) v.currentTime = next.source_in; else { v.pause(); setRoughCut(false); }
      }
    } else if (stopAt.current != null && v.currentTime >= stopAt.current) {
      v.pause(); stopAt.current = null;
    }
  };
  const playRoughCut = () => {
    const v = videoRef.current;
    if (!v || !plan?.segments.length) return;
    stopAt.current = null;
    setRoughCut(true);
    v.currentTime = plan.segments[0].source_in;
    v.play().catch(() => {});
  };

  const apply = async (then: "editor" | "export") => {
    if (!plan || !mediaId || !project) return;
    const clips = project.timeline.tracks.reduce((n, t) => n + t.clips.length, 0);
    if (clips && !confirm(`This replaces the ${clips} clip(s) currently on "${project.name}"'s timeline with the AI rough cut. The current edit is saved as a version first (Editor → History), so you can go back. Continue?`)) return;
    setApplying(true);
    try {
      const r = await autoedit.apply(projectId, mediaId, settings, plan.output_duration, extras);
      const done = r.extras.filter((n) => n.ok).map((n) => `${n.step}: ${n.detail}`);
      const skipped = r.extras.filter((n) => !n.ok).map((n) => `${n.step} ${n.detail}`);
      if (done.length) toast(done.join(" · "));
      skipped.forEach((t) => toast(t, true));
      localStorage.setItem("cf:lastProject", projectId);
      go(`${then}/${projectId}`);
    } catch (e: any) { toast(e.message, true); } finally { setApplying(false); }
  };

  const shown = useMemo(() => (plan?.beats ?? []).filter((b) => filter === "all" || (filter === "kept") === b.selected), [plan, filter]);
  if (!project) return <div className="page muted">Loading…</div>;
  if (!project.media.length) return <div className="page"><h1>AI Auto Editor</h1><div className="empty">This project has no media. <a href={`#/editor/${projectId}`}>Import some in the editor</a>.</div></div>;

  const minutes = Math.floor(settings.target_seconds / 60), seconds = Math.round(settings.target_seconds % 60);

  return (
    <div className="page" style={{ maxWidth: 1400 }}>
      <div className="row" style={{ marginBottom: 16 }}>
        <div className="grow"><h1>AI Auto Editor</h1><div className="muted">{project.name}</div></div>
        <a className="btn" href="#/auto/">Change project</a>
      </div>

      <div className="grid" style={{ gridTemplateColumns: "minmax(380px, 1fr) 1.25fr", alignItems: "start" }}>
        {/* ---------------- left: source + settings */}
        <div className="grid">
          <div className="card grid" style={{ gap: 10 }}>
            <div className="row">
              <h3 style={{ margin: 0 }}>Source</h3><span className="spacer" />
              {project.media.length > 1 && (
                <select value={mediaId ?? ""} onChange={(e) => setMediaId(e.target.value)} style={{ maxWidth: 260 }}>
                  {project.media.map((m) => <option key={m.id} value={m.id}>{m.original_name}</option>)}
                </select>
              )}
            </div>
            {media && (
              <>
                <video ref={videoRef} src={mediaUrl(projectId, media.id)} controls preload="metadata" onTimeUpdate={onTime}
                  style={{ width: "100%", aspectRatio: "16/9", background: "#000", borderRadius: 8 }} />
                <div className="muted" style={{ fontSize: 12 }}>
                  {media.original_name} · {fmtTime(media.duration, false)}
                  {media.has_video && ` · ${media.width}×${media.height} · ${media.fps ? Math.round(media.fps * 100) / 100 : "?"} fps`}
                  {!media.has_audio && " · no audio"}
                </div>
              </>
            )}
          </div>

          {!analyzed ? (
            <div className="card grid" style={{ gap: 10 }}>
              <h3 style={{ margin: 0 }}>1 · Analyse</h3>
              <div className="muted" style={{ fontSize: 12 }}>
                Measures loudness, pauses, on-screen motion and scene cuts. Runs locally — about
                {media ? ` ${Math.max(1, Math.ceil((media.duration / 60) * 4 / 60))} min` : " a minute"} for this file on a typical 2-core laptop (faster with more cores).
                {status && (status.transcriber
                  ? ` Speech will also be transcribed with ${status.transcriber} (experimental).`
                  : " No transcriber is installed, so editing uses sound and picture signals only.")}
              </div>
              {job && <JobRow job={job} onChange={refresh} />}
              {!jobActive && (
                <button className="btn primary" onClick={async () => {
                  try { await autoedit.analyze(projectId, mediaId!); refresh(); } catch (e: any) { toast(e.message, true); }
                }}><Icon name="wand" />{job?.status === "failed" ? "Try again" : "Analyse recording"}</button>
              )}
            </div>
          ) : (
            <div className="card grid" style={{ gap: 12 }}>
              <h3 style={{ margin: 0 }}>2 · Settings</h3>
              <label className="field">Target length
                <select value={settings.target_mode} onChange={(e) => set({ target_mode: e.target.value as any })}>
                  <option value="duration">Custom duration</option>
                  <option value="percent">Percentage of the original</option>
                  <option value="original">Original length (only remove dead air)</option>
                </select>
              </label>
              {settings.target_mode === "duration" && (
                <div className="row">
                  <label className="field" style={{ width: 90 }}>Minutes<input type="number" min={0} max={600} value={minutes}
                    onChange={(e) => set({ target_seconds: Math.max(1, Math.max(0, +e.target.value || 0) * 60 + seconds) })} /></label>
                  <label className="field" style={{ width: 90 }}>Seconds<input type="number" min={0} max={59} value={seconds}
                    onChange={(e) => set({ target_seconds: Math.max(1, minutes * 60 + Math.min(59, Math.max(0, +e.target.value || 0))) })} /></label>
                  <span className="spacer" />
                  {[60, 300, 600, 1800].map((v) => (
                    <button key={v} className={"btn sm" + (settings.target_seconds === v ? " on" : "")} onClick={() => set({ target_seconds: v })}>
                      {v < 60 ? `${v}s` : `${v / 60} min`}</button>
                  ))}
                </div>
              )}
              {settings.target_mode === "percent" && (
                <label className="field">Keep <span className="mono" style={{ color: "var(--text)" }}>{settings.target_percent}%</span>
                  <input type="range" min={5} max={100} step={5} value={settings.target_percent} onChange={(e) => set({ target_percent: +e.target.value })} />
                </label>
              )}
              <label className="field">Editing style
                <select value={settings.style} onChange={(e) => set({ style: e.target.value as any })}>
                  {STYLES.map(([v, l, d]) => <option key={v} value={v}>{l} — {d}</option>)}
                </select>
              </label>
              <label className="field">Pauses & dead air
                <select value={settings.silence} onChange={(e) => set({ silence: e.target.value as any })}>
                  {SILENCE.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                </select>
              </label>
              <label className="row" style={{ fontSize: 12 }}><input type="checkbox" checked={settings.keep_opening} onChange={(e) => set({ keep_opening: e.target.checked })} />Always keep the opening (hook)</label>
              <label className="row" style={{ fontSize: 12 }}><input type="checkbox" checked={settings.context} onChange={(e) => set({ context: e.target.checked })} />Keep setup right before chosen moments (context)</label>
              {(settings.include.length > 0 || settings.exclude.length > 0) && (
                <button className="btn sm" onClick={() => set({ include: [], exclude: [] })}>Reset my keep/drop choices ({settings.include.length + settings.exclude.length})</button>
              )}
              <button className="btn sm ghost" onClick={async () => { await autoedit.analyze(projectId, mediaId!); setStatus(null); refresh(); loadStatus(); }}>Re-analyse</button>
            </div>
          )}
          {analyzed && (
            <div className="card grid" style={{ gap: 8 }} data-testid="extras">
              <h3 style={{ margin: 0 }}>Finishing touches <span className="muted" style={{ fontWeight: 400, fontSize: 12 }}>— applied with the edit</span></h3>
              <label className="row" style={{ fontSize: 12 }}>
                <input type="checkbox" checked={extras.censor} onChange={(e) => setExtras({ censor: e.target.checked })} />Bleep swear words with
                <select value={extras.censor_sound} disabled={!extras.censor} onChange={(e) => setExtras({ censor_sound: e.target.value as Extras["censor_sound"] })}>
                  {["beep", "boing", "scratch", "honk", "quack", "mute"].map((v) => <option key={v} value={v}>{v === "mute" ? "silence" : `a ${v}`}</option>)}
                </select>
              </label>
              <label className="row" style={{ fontSize: 12 }}>Comedy edits on reactions
                <select value={extras.fun} onChange={(e) => setExtras({ fun: e.target.value as Extras["fun"] })}>
                  <option value="off">Off</option><option value="minimal">Minimal</option><option value="balanced">Balanced</option><option value="chaotic">Chaotic</option>
                </select>
              </label>
              <label className="row" style={{ fontSize: 12 }}><input type="checkbox" checked={extras.captions} onChange={(e) => setExtras({ captions: e.target.checked })} />Captions</label>
              <label className="row" style={{ fontSize: 12 }}><input type="checkbox" checked={extras.audio_polish} onChange={(e) => setExtras({ audio_polish: e.target.checked })} />Audio polish (YouTube loudness + voice enhance)</label>
              {(extras.censor || extras.captions) && !hasTranscript && (
                <div className="muted" style={{ fontSize: 11 }}>
                  <Icon name="warn" size={12} /> Bleeps and captions need a transcript of the speech.
                  {status?.transcriber ? " Re-analyse to transcribe it, or transcribe from Editor → Effects." : " Install the free transcriber (see README → Transcription), then re-analyse."} Without one they're skipped.
                </div>
              )}
              <div className="muted" style={{ fontSize: 11 }}>Every touch shows up in Editor → Effects, where you can tweak or delete it.</div>
            </div>
          )}
        </div>

        {/* ---------------- right: review */}
        <div className="card grid" style={{ gap: 12, minHeight: 300 }}>
          <div className="row"><h3 style={{ margin: 0 }}>3 · Review</h3>{planning && <span className="chip run">updating…</span>}</div>
          {!analyzed && <div className="muted">Analyse the recording to see the proposed edit.</div>}
          {planError && <div className="chip err">{planError}</div>}
          {plan && analyzed && (
            <>
              <div className="grid" style={{ gridTemplateColumns: "repeat(4, 1fr)", gap: 10 }}>
                {[["Original", plan.source_duration], ["Usable (no dead air)", plan.usable_duration],
                  ["Target", plan.target_duration], ["Your video", plan.output_duration]].map(([l, v]) => (
                  <div key={l as string} style={{ background: "var(--panel-2)", borderRadius: 8, padding: "8px 10px" }}>
                    <div className="muted" style={{ fontSize: 11 }}>{l}</div>
                    <div className="mono" style={{ fontSize: 17, fontWeight: 600, color: l === "Your video" ? "var(--accent-2)" : undefined }}>{fmtTime(Math.round(v as number), false)}</div>
                  </div>
                ))}
              </div>
              {plan.warnings.map((w) => <div key={w} className="banner" style={{ borderRadius: 8, border: "1px solid rgba(242,184,75,.4)" }}><Icon name="warn" size={14} />{w}</div>)}
              <Strip plan={plan} active={active} onPick={(b) => { setActive(b.id); playRange(b.start, b.end); }} />
              <div className="row">
                <button className="btn" disabled={!plan.segments.length} onClick={playRoughCut}><Icon name="play" size={14} />Play rough cut</button>
                <span className="muted" style={{ fontSize: 12 }}>{plan.beats.filter((b) => b.selected).length} of {plan.beats.length} moments · {plan.segments.length} cuts</span>
                <span className="spacer" />
                <select value={filter} onChange={(e) => setFilter(e.target.value as any)}>
                  <option value="all">All moments</option><option value="kept">Kept</option><option value="dropped">Left out</option>
                </select>
              </div>
              <div style={{ maxHeight: 460, overflow: "auto", border: "1px solid var(--line)", borderRadius: 8 }}>
                {shown.slice(0, 600).map((b) => {
                  const ov = overrideOf(b.id);
                  return (
                    <div key={b.id} onClick={() => setActive(b.id)}
                      style={{ display: "grid", gridTemplateColumns: "30px 120px 1fr 160px", gap: 10, alignItems: "center", padding: "8px 10px",
                        borderBottom: "1px solid var(--line)", background: active === b.id ? "var(--panel-2)" : undefined, opacity: b.selected ? 1 : 0.6 }}>
                      <button className="btn icon ghost" title="Preview this moment" onClick={(e) => { e.stopPropagation(); setActive(b.id); playRange(b.start, b.end); }}><Icon name="play" size={13} /></button>
                      <div className="mono" style={{ fontSize: 11 }}>{fmtTime(b.start, false)}–{fmtTime(b.end, false)}<div className="muted">{b.kept.toFixed(1)}s kept</div></div>
                      <div style={{ minWidth: 0 }}>
                        <div className="row" style={{ gap: 6 }}>
                          <div className="bar" style={{ width: 70, flex: "none" }}><div style={{ width: `${b.score}%`, background: b.selected ? "var(--accent)" : "var(--dim)" }} /></div>
                          <span className="mono" style={{ fontSize: 11 }}>{Math.round(b.score)}</span>
                          <span className={"chip" + (b.selected ? " ok" : "")}>{b.selected ? "kept" : "left out"}</span>
                          <span className="muted ellipsis" style={{ fontSize: 11 }}>{b.why}</span>
                        </div>
                        <div className="muted ellipsis" style={{ fontSize: 11, marginTop: 2 }}>{b.reasons.join(" · ")}</div>
                      </div>
                      <div className="row" style={{ gap: 2 }} onClick={(e) => e.stopPropagation()}>
                        {(["auto", "keep", "drop"] as const).map((v) => (
                          <button key={v} className={"btn sm" + (ov === v ? " on" : " ghost")} onClick={() => setOverride(b.id, v)}>{v === "auto" ? "Auto" : v === "keep" ? "Keep" : "Drop"}</button>
                        ))}
                      </div>
                    </div>
                  );
                })}
                {shown.length > 600 && <div className="muted" style={{ padding: 10, fontSize: 12 }}>Showing the first 600 of {shown.length} moments. Use the strip above to jump to any moment.</div>}
                {shown.length === 0 && <div className="muted" style={{ padding: 10 }}>Nothing here.</div>}
              </div>
              <div className="row">
                <span className="muted" style={{ fontSize: 12 }}>Nothing is rendered yet. Your original file is never changed.</span>
                <span className="spacer" />
                <button className="btn" disabled={applying || planning || !plan.segments.length} onClick={() => apply("export")}><Icon name="export" size={14} />Apply & export</button>
                <button className="btn primary" disabled={applying || planning || !plan.segments.length} onClick={() => apply("editor")}><Icon name="film" size={14} />{applying ? "Applying…" : "Send to Manual Editor"}</button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

const EXTRAS_DEFAULT: Extras = { censor: true, censor_sound: "beep", fun: "off", captions: false, audio_polish: true };

export default function AutoEditor({ projectId }: { projectId?: string }) {
  return projectId ? <Workspace key={projectId} projectId={projectId} /> : <ProjectPicker />;
}
