import React, { useEffect, useRef, useState } from "react";
import { api, ApiError, fmtBytes, type ExportItem, type Job, type ProjectSummary } from "../api";
import { Icon, JobRow, useJobs, useToast } from "../components/ui";
import { go } from "../router";

const H = { "X-RJClip": "1", "Content-Type": "application/json" };
async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const r = await fetch(path, { method, headers: H, body: body === undefined ? undefined : JSON.stringify(body) });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new ApiError(d.error || `Request failed (${r.status})`, r.status, d);
  return d as T;
}

interface Chapter { t: number; title: string }
interface Draft {
  title: string; description: string; tags: string[]; chapters: Chapter[]; privacy: "private" | "unlisted" | "public";
  category_id: string; made_for_kids: boolean; publish_at: string | null; export_file: string | null; thumbnail_file: string | null;
}
interface Suggest { titles: string[]; description: string; chapters: Chapter[]; tags: string[]; warnings: string[]; source: string; ai_model?: string; chapter_problems: string[] }
interface YTStatus { client_configured: boolean; connected: boolean; channel: { id: string; title: string } | null }

const fmt = (t: number) => { const s = Math.round(t), h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), x = s % 60; return h ? `${h}:${String(m).padStart(2, "0")}:${String(x).padStart(2, "0")}` : `${m}:${String(x).padStart(2, "0")}`; };
const parseTs = (v: string) => { const p = v.trim().split(":").map(Number); if (p.some(isNaN)) return null; return p.reduce((a, b) => a * 60 + b, 0); };
const tagChars = (tags: string[]) => tags.reduce((n, t) => n + t.length + (t.includes(" ") ? 3 : 1), 0);

function Picker() {
  const [projects, setProjects] = useState<ProjectSummary[] | null>(null);
  useEffect(() => { api.projects().then(setProjects).catch(() => setProjects([])); }, []);
  return (
    <div className="page" style={{ maxWidth: 900 }}>
      <h1>Publish</h1>
      <p className="muted">Write the title, description, chapters and tags from what you say, then upload to YouTube with your own account.</p>
      {projects === null ? <div className="muted">Loading…</div> : (
        <table className="list"><tbody>
          {projects.filter((p) => !p.error && p.clip_count).map((p) => (
            <tr key={p.id}><td><strong>{p.name}</strong></td><td className="muted">{fmt(p.duration)}</td>
              <td style={{ textAlign: "right" }}><button className="btn sm" onClick={() => go(`publish/${p.id}`)}>Choose</button></td></tr>
          ))}
        </tbody></table>
      )}
    </div>
  );
}

function Workspace({ projectId }: { projectId: string }) {
  const [name, setName] = useState("");
  const [duration, setDuration] = useState(0);
  const [markerCount, setMarkerCount] = useState(0);
  const [chapterSrc, setChapterSrc] = useState<"auto" | "markers">("auto");
  const [draft, setDraft] = useState<Draft | null>(null);
  const [cats, setCats] = useState<Record<string, string>>({});
  const [sug, setSug] = useState<Suggest | null>(null);
  const [writing, setWriting] = useState<"" | "rules" | "ai">("");
  const [ai, setAi] = useState<{ model: string | null; external: boolean; help: string | null } | null>(null);
  const [problems, setProblems] = useState<string[]>([]);
  const [saved, setSaved] = useState(true);
  const [exports, setExports] = useState<ExportItem[]>([]);
  const [thumbs, setThumbs] = useState<string[]>([]);
  const [yt, setYt] = useState<YTStatus | null>(null);
  const [uploads, setUploads] = useState<any[]>([]);
  const [tagInput, setTagInput] = useState("");
  const { jobs, refresh } = useJobs(projectId);
  const toast = useToast();
  const clientFile = useRef<HTMLInputElement>(null);
  const first = useRef(true);

  const loadYt = () => call<YTStatus>("GET", "/api/youtube/status").then(setYt).catch(() => {});
  const loadUploads = () => call<{ uploads: any[] }>("GET", `/api/projects/${projectId}/youtube/uploads`).then((r) => setUploads(r.uploads)).catch(() => {});
  useEffect(() => {
    api.project(projectId).then((p) => {
      setName(p.name);
      const n = p.timeline.markers?.length ?? 0;
      setMarkerCount(n); if (n) setChapterSrc("markers"); setDuration(p.timeline.tracks.reduce((m, t) => Math.max(m, ...t.clips.map((c) => c.start + (c.source_out - c.source_in) / c.speed)), 0)); });
    call<{ draft: Draft; categories: Record<string, string> }>("GET", `/api/projects/${projectId}/publish`).then((r) => { setDraft(r.draft); setCats(r.categories); });
    api.exports(projectId).then(setExports).catch(() => {});
    call<{ exports: { file: string }[] }>("GET", `/api/projects/${projectId}/thumbnails/exports`).then((r) => setThumbs(r.exports.map((e) => e.file))).catch(() => {});
    call<any>("GET", "/api/ai/status").then(setAi).catch(() => {});
    loadYt(); loadUploads();
  }, [projectId]);

  // autosave the draft
  useEffect(() => {
    if (!draft) return;
    if (first.current) { first.current = false; return; }
    setSaved(false);
    const t = setTimeout(() => {
      call<{ chapter_problems: string[] }>("PUT", `/api/projects/${projectId}/publish`, draft)
        .then((r) => { setProblems(r.chapter_problems); setSaved(true); })
        .catch((e) => toast(e.message, true));
    }, 600);
    return () => clearTimeout(t);
  }, [draft]);

  // poll while the Google sign-in tab is open
  const [waitingSignIn, setWaitingSignIn] = useState(false);
  useEffect(() => {
    if (!waitingSignIn) return;
    const t = setInterval(() => call<YTStatus>("GET", "/api/youtube/status").then((s) => { setYt(s); if (s.connected) { setWaitingSignIn(false); toast("YouTube connected"); } }), 2000);
    return () => clearInterval(t);
  }, [waitingSignIn]);

  const upJob = jobs.find((j) => j.kind === "youtube_upload");
  const upActive = upJob && (upJob.status === "queued" || upJob.status === "running");
  useEffect(() => { if (upJob?.status === "succeeded") loadUploads(); }, [upJob?.status]);

  if (!draft) return <div className="page muted">Loading…</div>;
  const set = (p: Partial<Draft>) => setDraft((d) => (d ? { ...d, ...p } : d));

  const write = async (useAi: boolean) => {
    setWriting(useAi ? "ai" : "rules");
    try {
      const r = await call<Suggest>("POST", `/api/projects/${projectId}/publish/suggest`, { use_ai: useAi, chapters: markerCount ? chapterSrc : "auto" });
      setSug(r);
      set({ title: draft.title || r.titles[0] || "", description: r.description, chapters: r.chapters, tags: r.tags });
      r.warnings.forEach((w) => toast(w, true));
      toast(r.source === "ai" ? `Written with ${r.ai_model}` : (r as any).chapters_from === "markers" ? "Written — chapters come from your markers" : "Written from your transcript");
    } catch (e: any) { toast(e.message, true); } finally { setWriting(""); }
  };

  const addTags = (raw: string) => {
    const add = raw.split(",").map((t) => t.trim()).filter(Boolean);
    const next = [...draft.tags];
    for (const t of add) if (!next.includes(t)) next.push(t.slice(0, 30));
    if (tagChars(next) > 500) return toast("Tags can be 500 characters at most", true);
    set({ tags: next }); setTagInput("");
  };

  const upload = async () => {
    const file = draft.export_file;
    if (!file) return toast("Choose which export to upload", true);
    if (!draft.title.trim()) return toast("Add a title first", true);
    const when = draft.publish_at ? `scheduled for ${new Date(draft.publish_at).toLocaleString()}` : draft.privacy.toUpperCase();
    if (!confirm(`Upload “${file}” to ${yt?.channel?.title ?? "your channel"} as ${when}?\n\nTitle: ${draft.title}`)) return;
    try { await call<Job>("POST", `/api/projects/${projectId}/youtube/upload`, { confirm: true, export_file: file }); refresh(); }
    catch (e: any) { toast(e.message, true); }
  };

  const okExports = exports.filter((e) => e.validation?.ok !== false);
  const localNow = new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 16);

  return (
    <div className="page" style={{ maxWidth: 1300 }}>
      <div className="row" style={{ marginBottom: 14 }}>
        <div className="grow"><h1>Publish</h1><div className="muted">{name} · {fmt(duration)} · <span className={saved ? "" : "dim"}>{saved ? "draft saved" : "saving…"}</span></div></div>
        <a className="btn" href="#/publish/">Change project</a>
      </div>
      <div className="grid" style={{ gridTemplateColumns: "minmax(420px, 1.3fr) 1fr", alignItems: "start" }}>
        {/* ---------------- details */}
        <div className="card grid" style={{ gap: 12 }} data-testid="details">
          <div className="row" style={{ gap: 6, flexWrap: "wrap" }}>
            <h3 style={{ margin: 0 }}>Video details</h3><span className="spacer" />
            <button className="btn sm" disabled={!!writing} onClick={() => write(false)}><Icon name="wand" size={13} />{writing === "rules" ? "Writing…" : "Write it for me"}</button>
            {ai?.model && <button className="btn sm" disabled={!!writing} onClick={() => write(true)}><Icon name="wand" size={13} />{writing === "ai" ? "Thinking…" : `Write with local AI (${ai.model})`}</button>}
          </div>
          {markerCount > 0 && (
            <label className="row" style={{ gap: 6, fontSize: 12 }}>Chapters
              <select value={chapterSrc} onChange={(e) => setChapterSrc(e.target.value as "auto" | "markers")} aria-label="Chapters from">
                <option value="markers">From my {markerCount} timeline marker{markerCount === 1 ? "" : "s"} (their names)</option>
                <option value="auto">Found from what's said</option>
              </select>
            </label>
          )}
          <div className="dim" style={{ fontSize: 11 }}>Written from what's said in your <em>final edit</em> (cut parts never show up). Swear words are left out.{!ai?.model && ai?.help ? ` For catchier wording, a free local AI can help: ${ai.help}` : ""}</div>
          <label className="field">Title <span className="mono dim">{draft.title.length}/100</span>
            <input type="text" value={draft.title} maxLength={100} onChange={(e) => set({ title: e.target.value })} aria-label="Title" />
          </label>
          {sug && sug.titles.length > 1 && (
            <div className="row" style={{ gap: 4, flexWrap: "wrap" }}>
              <span className="dim" style={{ fontSize: 11 }}>Ideas:</span>
              {sug.titles.map((t) => <button key={t} className={"btn xs" + (t === draft.title ? " on" : " ghost")} onClick={() => set({ title: t })}>{t}</button>)}
            </div>
          )}
          <label className="field">Description <span className="mono dim">{draft.description.length}/5000</span>
            <textarea rows={8} value={draft.description} maxLength={5000} onChange={(e) => set({ description: e.target.value })} aria-label="Description" />
          </label>
          <div className="grid" style={{ gap: 4 }}>
            <div className="row"><strong style={{ fontSize: 12 }}>Chapters</strong><span className="spacer" />
              <button className="btn xs ghost" onClick={() => set({ chapters: [...draft.chapters, { t: draft.chapters.length ? Math.min(duration - 10, draft.chapters[draft.chapters.length - 1].t + 30) : 0, title: "New chapter" }] })}><Icon name="plus" size={11} />Add</button></div>
            {draft.chapters.length === 0 && <div className="dim" style={{ fontSize: 11 }}>No chapters. “Write it for me” finds them from the topics you talk about (videos over a minute).</div>}
            {draft.chapters.map((c, i) => (
              <div key={i} className="row" style={{ gap: 4 }} data-testid="chapter">
                <input type="text" defaultValue={fmt(c.t)} key={`${i}-${c.t}`} style={{ width: 70 }} aria-label="Chapter time"
                  onBlur={(e) => { const t = parseTs(e.target.value); if (t === null) { e.target.value = fmt(c.t); return; } set({ chapters: draft.chapters.map((x, k) => (k === i ? { ...x, t } : x)).sort((a, b) => a.t - b.t) }); }} />
                <input type="text" value={c.title} maxLength={100} style={{ flex: 1, minWidth: 0 }} aria-label="Chapter title"
                  onChange={(e) => set({ chapters: draft.chapters.map((x, k) => (k === i ? { ...x, title: e.target.value } : x)) })} />
                <button className="btn icon ghost xs" title="Remove" onClick={() => set({ chapters: draft.chapters.filter((_, k) => k !== i) })}><Icon name="x" size={11} /></button>
              </div>
            ))}
            {problems.map((p) => <div key={p} className="chip warn">{p}</div>)}
            {draft.chapters.length > 0 && <div className="dim" style={{ fontSize: 11 }}>Chapters are added to the end of the description when you upload (unless it already lists them).</div>}
          </div>
          <div className="grid" style={{ gap: 4 }}>
            <div className="row"><strong style={{ fontSize: 12 }}>Tags</strong><span className="spacer" /><span className="mono dim" style={{ fontSize: 11 }}>{tagChars(draft.tags)}/500</span></div>
            <div className="row" style={{ gap: 4, flexWrap: "wrap" }}>
              {draft.tags.map((t) => <span key={t} className="chip tag">{t}<button className="btn icon ghost xs" onClick={() => set({ tags: draft.tags.filter((x) => x !== t) })}><Icon name="x" size={9} /></button></span>)}
            </div>
            <input type="text" value={tagInput} placeholder="Add tags, separated by commas" aria-label="Add tags"
              onChange={(e) => setTagInput(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" || e.key === ",") { e.preventDefault(); addTags(tagInput); } }} onBlur={() => tagInput && addTags(tagInput)} />
          </div>
          <div className="insp-grid">
            <label className="field">Category<select value={draft.category_id} onChange={(e) => set({ category_id: e.target.value })}>{Object.entries(cats).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
            <label className="field">Made for kids?<select value={draft.made_for_kids ? "yes" : "no"} onChange={(e) => set({ made_for_kids: e.target.value === "yes" })}><option value="no">No, it's not made for kids</option><option value="yes">Yes, it's made for kids</option></select></label>
          </div>
        </div>

        {/* ---------------- YouTube */}
        <div className="card grid" style={{ gap: 12 }} data-testid="youtube">
          <h3 style={{ margin: 0 }}>Upload to YouTube</h3>
          {!yt ? <div className="muted">…</div> : !yt.client_configured ? (
            <div className="grid" style={{ gap: 8, fontSize: 12 }}>
              <div>Uploads use <strong>your own</strong> free Google API access, so nothing goes through anyone else. One-time setup (~5 minutes):</div>
              <ol style={{ margin: 0, paddingLeft: 18, display: "grid", gap: 3 }}>
                <li>Open <span className="mono">console.cloud.google.com</span> → create a project.</li>
                <li>APIs &amp; Services → Library → enable <strong>YouTube Data API v3</strong>.</li>
                <li>OAuth consent screen → External → add your own Google account as a <strong>test user</strong>.</li>
                <li>Credentials → Create credentials → OAuth client ID → <strong>Desktop app</strong> → Download JSON.</li>
                <li>Choose that file here:</li>
              </ol>
              <button className="btn primary" onClick={() => clientFile.current?.click()}><Icon name="upload" size={14} />Choose the client JSON file</button>
              <input ref={clientFile} type="file" accept=".json,application/json" hidden onChange={async (e) => {
                const f = e.target.files?.[0]; e.target.value = ""; if (!f) return;
                try {
                  const r = await fetch("/api/youtube/client", { method: "POST", headers: { "X-RJClip": "1" }, body: f });
                  const d = await r.json(); if (!r.ok) throw new Error(d.error); setYt(d); toast("Client added — now connect your channel");
                } catch (err: any) { toast(err.message, true); }
              }} />
              <div className="dim" style={{ fontSize: 11 }}>Free: YouTube allows about 6 uploads a day per Google project. Details in docs/YOUTUBE.md.</div>
            </div>
          ) : !yt.connected ? (
            <div className="grid" style={{ gap: 8 }}>
              <button className="btn primary" onClick={async () => {
                try { const r = await call<{ url: string }>("POST", "/api/youtube/connect"); window.open(r.url, "_blank", "noopener"); setWaitingSignIn(true); }
                catch (e: any) { toast(e.message, true); }
              }}><Icon name="export" size={14} />Connect YouTube</button>
              {waitingSignIn && <div className="muted" style={{ fontSize: 12 }}>Finish signing in in the new tab… (Google may say the app isn't verified: it's your own app — choose Continue.)</div>}
              <button className="btn xs ghost" onClick={async () => { setYt(await call<YTStatus>("DELETE", "/api/youtube/client")); }}>Use a different client file</button>
            </div>
          ) : (
            <>
              <div className="row" style={{ gap: 6 }}><Icon name="check" size={14} /><span style={{ fontSize: 12 }}>Connected: <strong>{yt.channel?.title ?? "your channel"}</strong></span><span className="spacer" />
                <button className="btn xs ghost" onClick={async () => { if (confirm("Disconnect YouTube? RJClip forgets its access (you can connect again any time).")) setYt(await call<YTStatus>("POST", "/api/youtube/disconnect")); }}>Disconnect</button></div>
              <label className="field">Video
                <select value={draft.export_file ?? ""} onChange={(e) => set({ export_file: e.target.value || null })} aria-label="Video to upload">
                  <option value="">Choose an export…</option>
                  {okExports.map((e) => <option key={e.file} value={e.file}>{e.file} ({fmtBytes(e.size)})</option>)}
                </select>
              </label>
              {okExports.length === 0 && <div className="muted" style={{ fontSize: 12 }}>No exports yet. <a href={`#/export/${projectId}`}>Export the video</a> first.</div>}
              <label className="field">Thumbnail
                <select value={draft.thumbnail_file ?? ""} onChange={(e) => set({ thumbnail_file: e.target.value || null })}>
                  <option value="">None (YouTube picks a frame)</option>
                  {thumbs.map((t) => <option key={t} value={t}>{t}</option>)}
                </select>
              </label>
              <div className="field">Visibility
                <div className="row" style={{ gap: 4 }}>
                  {(["private", "unlisted", "public"] as const).map((v) => (
                    <button key={v} className={"btn sm" + (draft.privacy === v && !draft.publish_at ? " on" : " ghost")} onClick={() => set({ privacy: v, publish_at: null })}>
                      {v === "private" ? "Private" : v === "unlisted" ? "Unlisted" : "Public"}</button>
                  ))}
                </div>
              </div>
              <label className="field">Schedule (optional)
                <input type="datetime-local" min={localNow} value={draft.publish_at ? new Date(new Date(draft.publish_at).getTime() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 16) : ""}
                  onChange={(e) => set({ publish_at: e.target.value ? new Date(e.target.value).toISOString() : null })} />
              </label>
              {draft.publish_at && <div className="dim" style={{ fontSize: 11 }}>Uploads as private and goes public at that time.</div>}
              {upJob && (upActive || ["failed", "interrupted", "cancelled"].includes(upJob.status)) && <JobRow job={upJob} onChange={refresh} />}
              <button className="btn primary" disabled={!!upActive || !draft.export_file || !draft.title.trim()} onClick={upload} data-testid="upload">
                <Icon name="upload" size={14} />{upActive ? "Uploading…" : "Upload to YouTube"}</button>
            </>
          )}
          {uploads.length > 0 && (
            <div className="grid" style={{ gap: 4 }}>
              <strong style={{ fontSize: 12 }}>Uploaded</strong>
              {uploads.slice().reverse().map((u, i) => (
                <div key={i} className="row" style={{ gap: 6, fontSize: 12 }} data-testid="uploaded">
                  <span className="ellipsis grow">{u.title}</span><span className="chip">{u.privacy}</span>
                  {u.url && <a href={u.url} target="_blank" rel="noopener noreferrer">{u.url}</a>}
                  {u.thumbnail && u.thumbnail !== "set" && <span className="dim" title={u.thumbnail}>thumbnail {u.thumbnail.split(":")[0]}</span>}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default function Publish({ projectId }: { projectId?: string }) {
  return projectId ? <Workspace key={projectId} projectId={projectId} /> : <Picker />;
}
