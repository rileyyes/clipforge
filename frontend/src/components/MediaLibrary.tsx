import React, { useRef, useState } from "react";
import { api, fmtBytes, fmtTime, thumbUrl, uploadMedia, type Job } from "../api";
import type { MediaAsset, Project } from "../timeline/types";
import { ACCEPT } from "../pages/Dashboard";
import { Icon, useToast } from "./ui";

type Upload = { key: string; name: string; progress: number; phase: "uploading" | "checking" };

export default function MediaLibrary({ project, jobs, usedIds, onAdd, onChanged }: {
  project: Project; jobs: Job[]; usedIds: Set<string>;
  onAdd: (m: MediaAsset) => void; onChanged: () => void;
}) {
  const [uploads, setUploads] = useState<Upload[]>([]);
  const [over, setOver] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const toast = useToast();

  const upload = async (files: FileList | File[]) => {
    for (const file of Array.from(files)) {
      const key = Math.random().toString(36).slice(2);
      setUploads((u) => [...u, { key, name: file.name, progress: 0, phase: "uploading" }]);
      try {
        const r = await uploadMedia(project.id, file, (p) =>
          setUploads((u) => u.map((x) => (x.key === key ? { ...x, progress: p, phase: p >= 1 ? "checking" : "uploading" } : x))));
        toast(r.duplicate ? `${file.name} is already in this project` : `Imported ${file.name}`);
        onChanged();
      } catch (e: any) {
        toast(`${file.name}: ${e.message}`, true);
      } finally {
        setUploads((u) => u.filter((x) => x.key !== key));
      }
    }
  };

  const preparing = (m: MediaAsset) =>
    jobs.find((j) => j.kind === "derive_media" && j.params.media_id === m.id && (j.status === "running" || j.status === "queued"));
  const missing = new Set(project.missing_media ?? []);

  return (
    <div className="pane">
      <div className="pane-head">Media <span className="chip">{project.media.length}</span><span className="spacer" />
        <button className="btn sm" onClick={() => fileRef.current?.click()}><Icon name="upload" size={14} />Import</button>
      </div>
      <div className="pane-body"
        onDragOver={(e) => { if (e.dataTransfer.types.includes("Files")) { e.preventDefault(); setOver(true); } }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => { if (e.dataTransfer.files.length) { e.preventDefault(); setOver(false); upload(e.dataTransfer.files); } }}>
        <input ref={fileRef} type="file" accept={ACCEPT} multiple hidden
          onChange={(e) => { const f = e.target.files; if (f?.length) upload(Array.from(f)); e.target.value = ""; }} />
        {uploads.map((u) => (
          <div key={u.key} className="upload-row">
            <div className="row"><span className="ellipsis grow">{u.name}</span>
              <span className="muted mono">{u.phase === "checking" ? "checking…" : `${Math.round(u.progress * 100)}%`}</span></div>
            <div className={"bar" + (u.phase === "checking" ? " indeterminate" : "")}><div style={{ width: `${u.progress * 100}%` }} /></div>
          </div>
        ))}
        {project.media.length === 0 && uploads.length === 0 && (
          <div className={"dropzone" + (over ? " over" : "")} onClick={() => fileRef.current?.click()}>
            <Icon name="upload" size={22} /><div style={{ marginTop: 6 }}>Drop video or audio here</div>
            <div className="dim" style={{ fontSize: 11, marginTop: 4 }}>MP4, MOV, MKV, WebM, AVI, MP3, WAV, M4A…</div>
          </div>
        )}
        {project.media.map((m) => {
          const prep = preparing(m);
          return (
            <div key={m.id} className="media-item" draggable title="Drag onto the timeline, or double-click to append"
              onDragStart={(e) => { e.dataTransfer.setData("application/x-clipforge-media", m.id); e.dataTransfer.effectAllowed = "copy"; }}
              onDoubleClick={() => onAdd(m)}>
              <div className="media-thumb" style={m.thumbnail ? { backgroundImage: `url(${thumbUrl(project.id, m.id)})` } : {}}>
                {!m.thumbnail && <Icon name={m.has_video ? "film" : "music"} size={20} />}
                <span className="dur mono">{fmtTime(m.duration, false)}</span>
              </div>
              <div className="media-info">
                <div className="ellipsis" style={{ fontWeight: 600, fontSize: 12 }} title={m.original_name}>{m.original_name}</div>
                <div className="muted" style={{ fontSize: 11 }}>
                  {m.has_video ? `${m.width}×${m.height} · ${m.fps ? Math.round(m.fps * 100) / 100 : "?"} fps` : `${m.sample_rate ?? "?"} Hz audio`}
                  {" · "}{fmtBytes(m.size_bytes)}
                </div>
                <div className="row" style={{ gap: 4, flexWrap: "wrap" }}>
                  {missing.has(m.id) && <span className="chip err">file missing</span>}
                  {prep && <span className="chip run">{prep.stage}{prep.progress != null ? ` ${Math.round(prep.progress * 100)}%` : "…"}</span>}
                  {m.variable_frame_rate && <span className="chip warn" title="Variable frame rate is converted to constant on export">VFR</span>}
                  {usedIds.has(m.id) && <span className="chip">in use</span>}
                  <span className="spacer" />
                  <button className="btn sm ghost" title="Add to end of timeline" onClick={() => onAdd(m)}><Icon name="plus" size={14} /></button>
                  {!usedIds.has(m.id) && (
                    <button className="btn sm ghost danger" title="Remove from project" onClick={async () => {
                      if (!confirm(`Remove ${m.original_name} from this project?`)) return;
                      try { await api.deleteMedia(project.id, m.id); onChanged(); } catch (e: any) { toast(e.message, true); }
                    }}><Icon name="trash" size={14} /></button>
                  )}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
