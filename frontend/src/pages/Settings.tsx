import { tourAgain } from "../components/Tour";
import FontsCard from "../components/FontsCard";
import BrandKit from "../components/BrandKit";
import React, { useEffect, useState } from "react";
import { api, fmtBytes, type SystemInfo } from "../api";
import { useToast } from "../components/ui";

const ENV = [
  ["RJCLIP_WORKSPACE", "Where projects, media and exports are stored", "~/RJClipWorkspace (or an existing ~/ClipForgeWorkspace)"],
  ["RJCLIP_PORT", "Local port", "8765"],
  ["RJCLIP_MAX_UPLOAD_MB", "Largest single import", "20480"],
  ["RJCLIP_MAX_WORKSPACE_GB", "Workspace storage quota", "200"],
  ["RJCLIP_RENDER_TIMEOUT_S", "Max time for one processing step", "21600"],
  ["RJCLIP_JOB_WORKERS", "Parallel background jobs", "1"],
  ["RJCLIP_FFMPEG / RJCLIP_FFPROBE", "Custom FFmpeg binaries", "from PATH"],
];

export default function SettingsPage() {
  const [sys, setSys] = useState<SystemInfo | null>(null);
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  useEffect(() => { api.system().then(setSys).catch((e) => toast(e.message, true)); }, []);
  return (
    <div className="page" style={{ maxWidth: 900 }}>
      <h1>Settings</h1>
      <p className="muted">Settings are read from environment variables at startup so the web UI can never point the server at arbitrary folders.</p>
      <div className="grid" style={{ gridTemplateColumns: "1fr 1fr", marginTop: 18 }}>
        <div className="card">
          <h3>System</h3>
          {sys ? (
            <dl className="kv">
              <dt>Workspace</dt><dd className="mono ellipsis" title={sys.workspace}>{sys.workspace}</dd>
              <dt>FFmpeg</dt><dd className="ellipsis" title={sys.ffmpeg}>{sys.ffmpeg.replace("ffmpeg version ", "")}</dd>
              <dt>H.264 encoder</dt><dd>{sys.h264_encoder}{sys.h264_encoder === "libx264" && <span className="muted"> (software — no working GPU encoder found)</span>}</dd>
              <dt>CPU threads</dt><dd>{sys.cpu_count}</dd>
              <dt>Upload limit</dt><dd>{fmtBytes(sys.max_upload_bytes)}</dd>
              <dt>Workspace use</dt><dd>{fmtBytes(sys.workspace_bytes)} / {fmtBytes(sys.workspace_quota_bytes)}</dd>
              <dt>Disk free</dt><dd>{fmtBytes(sys.disk_free_bytes)}</dd>
              <dt>Render cache</dt><dd>{sys.render_cache_limit_bytes ? `${fmtBytes(sys.render_cache_bytes ?? 0)} / ${fmtBytes(sys.render_cache_limit_bytes)}` : "off"}<span className="muted"> — re-exports reuse unchanged parts</span></dd>
            </dl>
          ) : <span className="muted">Loading…</span>}
        </div>
        <div className="card">
          <h3>Maintenance</h3>
          <p className="muted" style={{ fontSize: 12, marginTop: 0 }}>Removes leftover temporary render files, interrupted partial files and the render cache (re-exports are slower until it refills). Projects, media and finished exports are never touched.</p>
          <button className="btn" disabled={busy} onClick={async () => {
            setBusy(true);
            try { const r = await api.cleanup(); toast(`Freed ${fmtBytes(r.freed_bytes)}`); api.system().then(setSys); }
            catch (e: any) { toast(e.message, true); } finally { setBusy(false); }
          }}>{busy ? "Cleaning…" : "Clean up temporary files"}</button>
        </div>
      </div>
      <div style={{ marginTop: 16 }}><FontsCard /></div>
      <div className="card" style={{ marginTop: 16 }}>
        <h3>Tour</h3>
        <p className="muted" style={{ fontSize: 12, marginTop: 0 }}>The short walk-through of the editor that you saw the first time.</p>
        <button className="btn" onClick={() => { tourAgain(); toast("The tour starts next time you open the editor"); }}>Show the tour again</button>
      </div>
      <div style={{ marginTop: 16 }}><BrandKit /></div>
      <div className="card" style={{ marginTop: 16 }}>
        <h3>Configuration</h3>
        <table className="list">
          <thead><tr><th>Variable</th><th>Purpose</th><th>Default</th></tr></thead>
          <tbody>{ENV.map(([k, d, v]) => <tr key={k}><td className="mono">{k}</td><td>{d}</td><td className="mono muted">{v}</td></tr>)}</tbody>
        </table>
      </div>
    </div>
  );
}
