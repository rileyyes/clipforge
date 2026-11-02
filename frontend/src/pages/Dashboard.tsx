import React, { useEffect, useRef, useState } from "react";
import { api, fmtBytes, fmtTime, thumbUrl, uploadMedia, type ProjectSummary, type SystemInfo } from "../api";
import { Icon, JobRow, PromptModal, useJobs, useToast } from "../components/ui";
import { go } from "../router";

export const ACCEPT = ".mp4,.m4v,.mov,.mkv,.webm,.avi,.mp3,.wav,.m4a,.aac,.flac,.ogg,.opus";

export function ProjectCard({ p }: { p: ProjectSummary }) {
  return (
    <div className="proj-card" onClick={() => go(`editor/${p.id}`)} role="button" tabIndex={0}
      onKeyDown={(e) => e.key === "Enter" && go(`editor/${p.id}`)}>
      <div className="proj-thumb" style={p.thumbnail_media_id ? { backgroundImage: `url(${thumbUrl(p.id, p.thumbnail_media_id)})` } : {}}>
        {!p.thumbnail_media_id && <Icon name="film" size={28} />}
      </div>
      <div className="proj-meta">
        <strong className="ellipsis">{p.name}</strong>
        <span className="muted" style={{ fontSize: 12 }}>
          {p.media_count} media · {p.clip_count} clips · {fmtTime(p.duration, false)}
        </span>
        <span className="dim" style={{ fontSize: 11 }}>Edited {new Date(p.updated_at).toLocaleString()}</span>
      </div>
    </div>
  );
}

export default function Dashboard() {
  const [projects, setProjects] = useState<ProjectSummary[] | null>(null);
  const [sys, setSys] = useState<SystemInfo | null>(null);
  const [naming, setNaming] = useState(false);
  const [importing, setImporting] = useState<{ name: string; p: number } | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const { jobs, refresh } = useJobs();
  const toast = useToast();

  useEffect(() => {
    api.projects().then(setProjects).catch((e) => toast(e.message, true));
    api.system().then(setSys).catch(() => {});
  }, []);

  const importVideo = async (file: File) => {
    try {
      const stem = file.name.replace(/\.[^.]+$/, "") || "New project";
      const proj = await api.createProject(stem.slice(0, 120));
      setImporting({ name: file.name, p: 0 });
      await uploadMedia(proj.id, file, (p) => setImporting({ name: file.name, p }));
      localStorage.setItem("cf:lastProject", proj.id);
      go(`editor/${proj.id}`);
    } catch (e: any) {
      toast(e.message, true);
      setImporting(null);
    }
  };

  const active = jobs.filter((j) => j.status === "running" || j.status === "queued");
  const recentDone = jobs.filter((j) => !active.includes(j)).slice(0, 5);
  const usedPct = sys ? Math.min(100, (sys.workspace_bytes / sys.workspace_quota_bytes) * 100) : 0;

  return (
    <div className="page">
      <h1>Dashboard</h1>
      <p className="muted" style={{ margin: 0 }}>Import a recording, cut it on the timeline, export a YouTube-ready MP4.</p>

      <div className="hero">
        <button className="action" onClick={() => setNaming(true)}>
          <Icon name="plus" /><strong>New project</strong><span>Start with an empty timeline</span>
        </button>
        <button className="action" onClick={() => fileRef.current?.click()} disabled={!!importing}>
          <Icon name="upload" /><strong>Import video</strong>
          <span>{importing ? `Uploading ${importing.name} — ${Math.round(importing.p * 100)}%` : "Creates a project and opens the editor"}</span>
        </button>
        <button className="action" onClick={() => go("editor")}>
          <Icon name="film" /><strong>Open manual editor</strong><span>Pick a project to edit</span>
        </button>
        <button className="action" disabled title="The automatic editing engine is Phase 3 of the roadmap">
          <Icon name="wand" /><strong>AI auto edit</strong><span>Coming in Phase 3 — not built yet</span>
        </button>
      </div>
      <input ref={fileRef} type="file" accept={ACCEPT} hidden
        onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) importVideo(f); }} />

      <div className="grid" style={{ gridTemplateColumns: "1fr 320px", alignItems: "start" }}>
        <section>
          <div className="row" style={{ marginBottom: 12 }}>
            <h2 style={{ margin: 0 }}>Recent projects</h2><span className="spacer" />
            <a href="#/projects" className="muted" style={{ fontSize: 12 }}>All projects →</a>
          </div>
          {projects === null ? <div className="muted">Loading…</div>
            : projects.length === 0 ? <div className="empty">No projects yet. Import a video to get started.</div>
              : <div className="proj-grid">{projects.slice(0, 8).map((p) => <ProjectCard key={p.id} p={p} />)}</div>}
        </section>

        <aside className="grid">
          <div className="card">
            <h3>Processing jobs</h3>
            {active.length === 0 && <div className="muted" style={{ fontSize: 12 }}>Nothing running.</div>}
            {active.map((j) => <JobRow key={j.id} job={j} onChange={refresh} />)}
            {recentDone.length > 0 && <div className="dim" style={{ fontSize: 11, marginTop: 10 }}>Recent</div>}
            {recentDone.map((j) => <JobRow key={j.id} job={j} onChange={refresh} compact />)}
          </div>
          <div className="card">
            <h3>Storage</h3>
            {sys ? (
              <div className="grid" style={{ gap: 8 }}>
                <div className="bar"><div style={{ width: `${usedPct}%` }} /></div>
                <div className="row" style={{ fontSize: 12 }}>
                  <span>{fmtBytes(sys.workspace_bytes)} used</span><span className="spacer" />
                  <span className="muted">quota {fmtBytes(sys.workspace_quota_bytes)}</span>
                </div>
                <div className="muted" style={{ fontSize: 12 }}>{fmtBytes(sys.disk_free_bytes)} free on disk</div>
              </div>
            ) : <div className="muted">…</div>}
          </div>
        </aside>
      </div>

      {naming && <PromptModal title="New project" label="Project name" initial="Untitled project"
        onClose={() => setNaming(false)}
        onSubmit={async (name) => {
          try { const p = await api.createProject(name); localStorage.setItem("cf:lastProject", p.id); go(`editor/${p.id}`); }
          catch (e: any) { toast(e.message, true); }
        }} />}
    </div>
  );
}
