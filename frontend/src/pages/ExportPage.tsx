import React, { useEffect, useMemo, useState } from "react";
import { api, exportUrl, fmtBytes, fmtTime, type ExportItem } from "../api";
import { Icon, JobRow, useJobs, useToast } from "../components/ui";
import { timelineDuration } from "../timeline/ops";
import type { OutputSettings, Project } from "../timeline/types";

const PRESETS = [
  { id: "1080", label: "YouTube 1080p · 16:9", w: 1920, h: 1080 },
  { id: "720", label: "720p · 16:9", w: 1280, h: 720 },
  { id: "4k", label: "4K UHD · 16:9", w: 3840, h: 2160 },
  { id: "vertical", label: "Shorts / Reels · 9:16", w: 1080, h: 1920 },
  { id: "square", label: "Square · 1:1", w: 1080, h: 1080 },
];
const FPS = [24, 25, 30, 50, 60];

export default function ExportPage({ projectId }: { projectId: string }) {
  const [project, setProject] = useState<Project | null>(null);
  const [out, setOut] = useState<OutputSettings | null>(null);
  const [filename, setFilename] = useState("");
  const [quality, setQuality] = useState("standard");
  const [exportsList, setExports] = useState<ExportItem[]>([]);
  const [preview, setPreview] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const { jobs, refresh } = useJobs(projectId);
  const toast = useToast();

  const loadExports = () => api.exports(projectId).then(setExports).catch(() => {});
  useEffect(() => {
    localStorage.setItem("cf:lastProject", projectId);
    api.project(projectId).then((p) => { setProject(p); setOut(p.output); setFilename(p.name); })
      .catch((e) => toast(e.message, true));
    loadExports();
  }, [projectId]);

  const renders = jobs.filter((j) => j.kind === "render");
  const running = renders.some((j) => j.status === "running" || j.status === "queued");
  const lastDone = renders.find((j) => j.status === "succeeded")?.id;
  useEffect(() => { loadExports(); }, [lastDone, running]);

  const duration = useMemo(() => (project ? timelineDuration(project.timeline) : 0), [project]);
  const preset = out ? PRESETS.find((p) => p.w === out.width && p.h === out.height)?.id ?? "custom" : "1080";

  if (!project || !out) return <div className="page muted">Loading…</div>;
  const missing = project.missing_media?.length ?? 0;

  return (
    <div className="page">
      <div className="row" style={{ marginBottom: 18 }}>
        <div className="grow"><h1>Export</h1><div className="muted">{project.name} · {fmtTime(duration)} on the timeline</div></div>
        <a className="btn" href={`#/editor/${projectId}`} style={{ textDecoration: "none" }}><Icon name="film" />Back to editor</a>
      </div>

      <div className="grid" style={{ gridTemplateColumns: "380px 1fr", alignItems: "start" }}>
        <div className="card grid" style={{ gap: 14 }}>
          <h3 style={{ margin: 0 }}>Output</h3>
          <label className="field">Format
            <select value={preset} onChange={(e) => {
              const p = PRESETS.find((x) => x.id === e.target.value);
              if (p) setOut({ ...out, width: p.w, height: p.h });
            }}>
              {PRESETS.map((p) => <option key={p.id} value={p.id}>{p.label} ({p.w}×{p.h})</option>)}
              {preset === "custom" && <option value="custom">Custom ({out.width}×{out.height})</option>}
            </select>
          </label>
          <div className="insp-grid">
            <label className="field">Width<input type="number" step={2} min={16} max={7680} value={out.width}
              onChange={(e) => setOut({ ...out, width: Math.round(+e.target.value / 2) * 2 })} /></label>
            <label className="field">Height<input type="number" step={2} min={16} max={4320} value={out.height}
              onChange={(e) => setOut({ ...out, height: Math.round(+e.target.value / 2) * 2 })} /></label>
            <label className="field">Frame rate
              <select value={out.fps} onChange={(e) => setOut({ ...out, fps: +e.target.value })}>
                {FPS.map((f) => <option key={f} value={f}>{f} fps</option>)}
              </select>
            </label>
            <label className="field">Quality
              <select value={quality} onChange={(e) => setQuality(e.target.value)}>
                <option value="draft">Draft (fast, small)</option>
                <option value="standard">Standard</option>
                <option value="high">High (larger file)</option>
              </select>
            </label>
          </div>
          <label className="field">When the shape doesn't match
            <select value={out.fit_mode} onChange={(e) => setOut({ ...out, fit_mode: e.target.value as any })}>
              <option value="fit">Letterbox — show the whole picture</option>
              <option value="fill">Crop — fill the frame</option>
            </select>
          </label>
          <label className="field">File name<input type="text" value={filename} maxLength={80} onChange={(e) => setFilename(e.target.value)} /></label>
          <div className="muted" style={{ fontSize: 12 }}>MP4 · H.264 video · AAC 192 kbps stereo audio. Footage is never stretched.</div>
          {missing > 0 && <div className="chip err">{missing} source file(s) missing</div>}
          <button className="btn primary" disabled={starting || running || duration <= 0 || missing > 0}
            onClick={async () => {
              setStarting(true);
              try { await api.startExport(projectId, { filename: filename || project.name, quality, output: out }); refresh(); }
              catch (e: any) { toast(e.message, true); } finally { setStarting(false); }
            }}>
            <Icon name="export" />{duration <= 0 ? "Timeline is empty" : running ? "Export running…" : "Export video"}
          </button>
        </div>

        <div className="grid">
          {renders.length > 0 && (
            <div className="card">
              <h3>Export jobs</h3>
              {renders.slice(0, 4).map((j) => <JobRow key={j.id} job={j} onChange={refresh} />)}
            </div>
          )}
          <div className="card">
            <h3>Finished exports</h3>
            {exportsList.length === 0 && <div className="muted" style={{ fontSize: 12 }}>No exports yet.</div>}
            {exportsList.map((x) => (
              <div key={x.file} style={{ padding: "12px 0", borderBottom: "1px solid var(--line)", display: "grid", gap: 8 }}>
                <div className="row">
                  <strong className="ellipsis">{x.file}</strong>
                  {x.validation && <span className={"chip " + (x.validation.ok ? "ok" : "err")}>{x.validation.ok ? "validated" : "validation failed"}</span>}
                  <span className="spacer" />
                  <span className="muted" style={{ fontSize: 12 }}>{fmtBytes(x.size)}</span>
                  <button className="btn sm" onClick={() => setPreview(preview === x.file ? null : x.file)}><Icon name="play" size={14} />Preview</button>
                  <a className="btn sm" href={exportUrl(projectId, x.file)} download style={{ textDecoration: "none" }}>Download</a>
                  <button className="btn sm ghost danger" title="Delete export" onClick={async () => {
                    if (!confirm(`Delete ${x.file}?`)) return;
                    await api.deleteExport(projectId, x.file); loadExports();
                  }}><Icon name="trash" size={14} /></button>
                </div>
                {preview === x.file && <video src={exportUrl(projectId, x.file, true)} controls style={{ width: "100%", maxHeight: 360, background: "#000", borderRadius: 8 }} />}
                {x.validation && (
                  <div className="checks">
                    {x.validation.checks.map((c) => (
                      <div key={c.check}><span style={{ color: c.ok ? "var(--ok)" : "var(--err)" }}>{c.ok ? "✓" : "✗"}</span>
                        <span>{c.check}</span><span className="muted mono" style={{ fontSize: 11 }}>{c.detail}</span></div>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
