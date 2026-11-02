import React, { useEffect, useState } from "react";
import { api, fmtTime, thumbUrl, type ProjectSummary } from "../api";
import { Icon, PromptModal, useToast } from "../components/ui";
import { go } from "../router";

export default function Projects({ pickFor }: { pickFor?: "editor" | "export" }) {
  const [projects, setProjects] = useState<ProjectSummary[] | null>(null);
  const [renaming, setRenaming] = useState<ProjectSummary | null>(null);
  const [creating, setCreating] = useState(false);
  const toast = useToast();
  const load = () => api.projects().then(setProjects).catch((e) => toast(e.message, true));
  useEffect(() => { load(); }, []);

  const open = (id: string) => {
    localStorage.setItem("cf:lastProject", id);
    go(`${pickFor ?? "editor"}/${id}`);
  };

  return (
    <div className="page">
      <div className="row" style={{ marginBottom: 18 }}>
        <div className="grow">
          <h1>{pickFor === "editor" ? "Open in Manual Editor" : pickFor === "export" ? "Choose a project to export" : "Projects"}</h1>
          <div className="muted">Projects are saved automatically as you edit.</div>
        </div>
        <button className="btn primary" onClick={() => setCreating(true)}><Icon name="plus" />New project</button>
      </div>
      {projects === null ? <div className="muted">Loading…</div> : projects.length === 0 ? (
        <div className="empty">No projects yet.</div>
      ) : (
        <table className="list">
          <thead><tr><th style={{ width: 96 }} /><th>Name</th><th>Length</th><th>Media</th><th>Last edited</th><th /></tr></thead>
          <tbody>
            {projects.map((p) => (
              <tr key={p.id}>
                <td>
                  <div className="media-thumb" style={{ width: 80, ...(p.thumbnail_media_id ? { backgroundImage: `url(${thumbUrl(p.id, p.thumbnail_media_id)})` } : {}) }}>
                    {!p.thumbnail_media_id && <Icon name="film" />}
                  </div>
                </td>
                <td><a href="#" onClick={(e) => { e.preventDefault(); if (!p.error) open(p.id); }}><strong>{p.name}</strong></a>
                  {p.error && <span className="chip err" style={{ marginLeft: 8 }}>unreadable</span>}</td>
                <td className="mono">{p.error ? "—" : fmtTime(p.duration, false)}</td>
                <td>{p.media_count ?? "—"}</td>
                <td className="muted">{p.updated_at ? new Date(p.updated_at).toLocaleString() : "—"}</td>
                <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                  <button className="btn sm" disabled={p.error} onClick={() => open(p.id)}>Open</button>{" "}
                  {!pickFor && <>
                    <button className="btn sm ghost" disabled={p.error} onClick={() => setRenaming(p)}>Rename</button>
                    <button className="btn sm ghost" disabled={p.error} onClick={async () => {
                      try { await api.duplicate(p.id); toast("Project duplicated"); load(); } catch (e: any) { toast(e.message, true); }
                    }}>Duplicate</button>
                    <button className="btn sm ghost danger" onClick={async () => {
                      if (!confirm(`Delete "${p.name}"? Its imported media and exports will be removed from the workspace. Your original files elsewhere on disk are not touched.`)) return;
                      try { await api.deleteProject(p.id); if (localStorage.getItem("cf:lastProject") === p.id) localStorage.removeItem("cf:lastProject"); load(); }
                      catch (e: any) { toast(e.message, true); }
                    }}>Delete</button>
                  </>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {renaming && <PromptModal title="Rename project" label="Name" initial={renaming.name} confirm="Rename"
        onClose={() => setRenaming(null)}
        onSubmit={async (name) => {
          try { await api.rename(renaming.id, name); setRenaming(null); load(); } catch (e: any) { toast(e.message, true); }
        }} />}
      {creating && <PromptModal title="New project" label="Project name" initial="Untitled project"
        onClose={() => setCreating(false)}
        onSubmit={async (name) => {
          try { const p = await api.createProject(name); open(p.id); } catch (e: any) { toast(e.message, true); }
        }} />}
    </div>
  );
}
