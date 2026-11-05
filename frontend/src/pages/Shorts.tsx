import React, { useEffect, useRef, useState } from "react";
import { api, autoedit, fmtTime, mediaUrl, type Job, type ProjectSummary } from "../api";
import { Icon, JobRow, useJobs, useToast } from "../components/ui";
import type { MediaAsset, Project } from "../timeline/types";
import { go } from "../router";

const H = { "X-ClipForge": "1", "Content-Type": "application/json" };
async function post<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(path, { method: "POST", headers: H, body: JSON.stringify(body) });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(d.error || `Request failed (${r.status})`);
  return d as T;
}

interface Suggestion { start: number; end: number; duration: number; score: number; reasons: string[]; hook: string; title: string }
const STYLES: [string, string][] = [["balanced", "Balanced"], ["humor", "Funniest"], ["reactions", "Biggest reactions"],
  ["excitement", "Most exciting"], ["story", "Best story"], ["information", "Most informative"], ["action", "Most action"]];

function Picker() {
  const [projects, setProjects] = useState<ProjectSummary[] | null>(null);
  const toast = useToast();
  useEffect(() => { api.projects().then(setProjects).catch((e) => toast(e.message, true)); }, []);
  return (
    <div className="page" style={{ maxWidth: 900 }}>
      <h1>Shorts</h1>
      <p className="muted">Turn the best moments of a video into vertical 9:16 Shorts that keep you in frame, with captions. Pick the project with the full video.</p>
      {projects === null ? <div className="muted">Loading…</div> : (
        <table className="list"><tbody>
          {projects.filter((p) => p.media_count && !p.error && !/— Short/.test(p.name)).map((p) => (
            <tr key={p.id}><td><strong>{p.name}</strong></td><td className="muted">{p.media_count} media</td>
              <td style={{ textAlign: "right" }}><button className="btn sm" onClick={() => go(`shorts/${p.id}`)}>Choose</button></td></tr>
          ))}
        </tbody></table>
      )}
    </div>
  );
}

function Workspace({ projectId }: { projectId: string }) {
  const [project, setProject] = useState<Project | null>(null);
  const [mediaId, setMediaId] = useState<string | null>(null);
  const [analyzed, setAnalyzed] = useState<boolean | null>(null);
  const [style, setStyle] = useState("balanced");
  const [len, setLen] = useState<[number, number]>([15, 60]);
  const [sugs, setSugs] = useState<Suggestion[] | null>(null);
  const [error, setError] = useState("");
  const [edits, setEdits] = useState<Record<number, { start: number; end: number; title: string }>>({});
  const [captions, setCaptions] = useState(true);
  const [follow, setFollow] = useState(true);
  const [camLayout, setCamLayout] = useState<"corner" | "stacked" | "none">("stacked");
  const [mine, setMine] = useState<string[]>([]);  // job ids started here
  const video = useRef<HTMLVideoElement>(null);
  const stopAt = useRef<number | null>(null);
  const { jobs, refresh } = useJobs(projectId);
  const toast = useToast();

  useEffect(() => {
    api.project(projectId).then((p) => { setProject(p); setMediaId((p.media.find((m) => m.has_video) ?? p.media[0])?.id ?? null); })
      .catch((e) => toast(e.message, true));
  }, [projectId]);
  const loadStatus = () => autoedit.status(projectId).then((s) => setAnalyzed(!!s.media.find((m) => m.media_id === mediaId)?.analyzed));
  useEffect(() => { if (mediaId) loadStatus(); }, [mediaId]);
  const aJob = jobs.find((j) => j.kind === "analyze" && j.params.media_id === mediaId);
  useEffect(() => { if (aJob?.status === "succeeded") loadStatus(); }, [aJob?.status]);

  useEffect(() => {
    if (!analyzed || !mediaId) return;
    setSugs(null); setError("");
    post<{ suggestions: Suggestion[] }>(`/api/projects/${projectId}/shorts/suggest`, { media_id: mediaId, count: 6, min_seconds: len[0], max_seconds: len[1], style })
      .then((r) => { setSugs(r.suggestions); setEdits({}); }).catch((e) => setError(e.message));
  }, [analyzed, mediaId, style, len[0], len[1]]);

  const media: MediaAsset | undefined = project?.media.find((m) => m.id === mediaId);
  const play = (a: number, b: number) => {
    const v = video.current;
    if (!v) return;
    stopAt.current = b; v.currentTime = a; v.play().catch(() => {});
  };
  const shortJobs = jobs.filter((j) => j.kind === "make_short" && (mine.includes(j.id) || j.status === "succeeded"));
  const make = async (i: number, s: Suggestion) => {
    const e = edits[i] ?? { start: s.start, end: s.end, title: s.title };
    try {
      const j = await post<Job>(`/api/projects/${projectId}/shorts`, { media_id: mediaId, start: e.start, end: e.end, title: e.title, captions, follow, facecam_layout: camLayout });
      setMine((m) => [...m, j.id]); refresh();
      toast("Making your Short… it appears below when ready");
    } catch (err: any) { toast(err.message, true); }
  };

  if (!project) return <div className="page muted">Loading…</div>;
  return (
    <div className="page" style={{ maxWidth: 1300 }}>
      <div className="row" style={{ marginBottom: 14 }}>
        <div className="grow"><h1>Shorts</h1><div className="muted">{project.name}</div></div>
        <a className="btn" href="#/shorts/">Change project</a>
      </div>
      <div className="grid" style={{ gridTemplateColumns: "minmax(360px, 1fr) 1.3fr", alignItems: "start" }}>
        <div className="grid">
          <div className="card grid" style={{ gap: 8 }}>
            {project.media.length > 1 && (
              <select value={mediaId ?? ""} onChange={(e) => setMediaId(e.target.value)}>{project.media.map((m) => <option key={m.id} value={m.id}>{m.original_name}</option>)}</select>
            )}
            {media && (
              <div style={{ position: "relative", overflow: "hidden", borderRadius: 8 }}>
                <video ref={video} src={mediaUrl(projectId, media.id)} controls preload="metadata"
                  onTimeUpdate={() => { const v = video.current; if (v && stopAt.current != null && v.currentTime >= stopAt.current) { v.pause(); stopAt.current = null; } }}
                  style={{ display: "block", width: "100%", aspectRatio: `${media.width || 16}/${media.height || 9}`, background: "#000", borderRadius: 8 }} />
                {media.width && media.height && media.width > media.height && (
                  <div className="short-frame" title="Roughly what fits in a Short — the real one follows you around"
                    style={{ width: `${(media.height * 9 / 16) / media.width * 100}%` }} />
                )}
              </div>
            )}
          </div>
          <div className="card grid" style={{ gap: 10 }}>
            <h3 style={{ margin: 0 }}>Settings</h3>
            <label className="field">Find the
              <select value={style} onChange={(e) => setStyle(e.target.value)}>{STYLES.map(([v, l]) => <option key={v} value={v}>{l} moments</option>)}</select>
            </label>
            <label className="field">Length
              <select value={len.join("-")} onChange={(e) => setLen(e.target.value.split("-").map(Number) as [number, number])}>
                <option value="15-30">15–30 seconds</option><option value="15-60">15–60 seconds</option><option value="30-60">30–60 seconds</option><option value="45-90">45–90 seconds</option>
              </select>
            </label>
            {project?.facecam && project.facecam.main_media_id === mediaId && (
              <label className="row" style={{ fontSize: 12 }}>Face cam
                <select value={camLayout} aria-label="Face cam layout" onChange={(e) => setCamLayout(e.target.value as any)}>
                  <option value="stacked">Stacked: face cam on top, video below</option>
                  <option value="corner">In its corner</option>
                  <option value="none">Leave it out</option>
                </select></label>
            )}
            {!(project?.facecam && project.facecam.main_media_id === mediaId && camLayout === "stacked") &&
              <label className="row" style={{ fontSize: 12 }}><input type="checkbox" checked={follow} onChange={(e) => setFollow(e.target.checked)} />Keep me in frame (follows your face, or what moves)</label>}
            <label className="row" style={{ fontSize: 12 }}><input type="checkbox" checked={captions} onChange={(e) => setCaptions(e.target.checked)} />Captions (needs a transcript)</label>
            <div className="dim" style={{ fontSize: 11 }}>Each Short becomes its own project (1080×1920) that shares this video's files — no extra disk space. Your bleeps and effects come along.</div>
          </div>
        </div>
        <div className="card grid" style={{ gap: 10 }} data-testid="shorts">
          <h3 style={{ margin: 0 }}>Best moments</h3>
          {analyzed === false && (
            <div className="grid" style={{ gap: 8 }}>
              <div className="muted">This video needs analysing first (sound, picture{" "}and speech).</div>
              {aJob && (aJob.status === "running" || aJob.status === "queued") ? <JobRow job={aJob} onChange={refresh} /> :
                <button className="btn primary" onClick={async () => { await autoedit.analyze(projectId, mediaId!); refresh(); }}><Icon name="wand" />Analyse video</button>}
            </div>
          )}
          {error && <div className="chip err">{error}</div>}
          {analyzed && !sugs && !error && <div className="muted">Finding moments…</div>}
          {sugs?.length === 0 && <div className="muted">No moment of that length found — try a shorter length.</div>}
          {sugs?.map((s, i) => {
            const e = edits[i] ?? { start: s.start, end: s.end, title: s.title };
            const set = (p: Partial<typeof e>) => setEdits((m) => ({ ...m, [i]: { ...e, ...p } }));
            return (
              <div key={`${s.start}-${s.end}`} className="short-row" data-testid="short-suggestion">
                <div className="row" style={{ gap: 6 }}>
                  <button className="btn icon ghost" title="Preview" onClick={() => play(e.start, e.end)}><Icon name="play" size={13} /></button>
                  <span className="mono" style={{ fontSize: 12 }}>{fmtTime(e.start, false)}–{fmtTime(e.end, false)}</span>
                  <span className="chip">{Math.round(e.end - e.start)} s</span>
                  <div className="bar" style={{ width: 60, flex: "none" }}><div style={{ width: `${s.score}%` }} /></div>
                  <span className="mono dim" style={{ fontSize: 11 }}>{Math.round(s.score)}</span>
                  <span className="spacer" />
                  <button className="btn sm primary" onClick={() => make(i, s)}><Icon name="film" size={13} />Make Short</button>
                </div>
                <div className="muted" style={{ fontSize: 11 }}>{s.reasons.join(" · ")}</div>
                {s.hook && <div style={{ fontSize: 12, fontStyle: "italic" }}>“{s.hook}”</div>}
                <div className="row" style={{ gap: 6 }}>
                  <input type="text" placeholder="Title (optional)" value={e.title} maxLength={80} onChange={(ev) => set({ title: ev.target.value })} style={{ flex: 1, minWidth: 0 }} aria-label="Short title" />
                  <button className="btn xs ghost" title="Start 1 s earlier" onClick={() => set({ start: Math.max(0, e.start - 1) })}>◀ start</button>
                  <button className="btn xs ghost" title="Start 1 s later" onClick={() => set({ start: Math.min(e.end - 3, e.start + 1) })}>start ▶</button>
                  <button className="btn xs ghost" title="End 1 s earlier" onClick={() => set({ end: Math.max(e.start + 3, e.end - 1) })}>◀ end</button>
                  <button className="btn xs ghost" title="End 1 s later" onClick={() => set({ end: Math.min(media?.duration ?? e.end + 1, e.end + 1) })}>end ▶</button>
                </div>
              </div>
            );
          })}
          {shortJobs.length > 0 && <h3 style={{ margin: "10px 0 0" }}>Your Shorts</h3>}
          {shortJobs.map((j) => (
            <div key={j.id} className="short-row" data-testid="short-job">
              {j.status === "succeeded" ? (
                <div className="row" style={{ gap: 6 }}>
                  <Icon name="check" size={14} /><strong style={{ fontSize: 12 }} className="ellipsis grow">{j.result.name}</strong>
                  <span className="muted" style={{ fontSize: 11 }}>{j.result.facecam === "custom" ? "stacked with face cam" : j.result.follow?.moves ? `follows you (${j.result.follow.moves} moves)` : "centred"}{j.result.captions ? " · captions" : ""}</span>
                  <a className="btn sm" href={`#/editor/${j.result.project_id}`}>Open</a>
                  <a className="btn sm primary" href={`#/export/${j.result.project_id}`}><Icon name="export" size={13} />Export</a>
                </div>
              ) : <JobRow job={j} onChange={refresh} />}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

export default function Shorts({ projectId }: { projectId?: string }) {
  return projectId ? <Workspace key={projectId} projectId={projectId} /> : <Picker />;
}
