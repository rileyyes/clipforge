import React, { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { api, type Job } from "../api";

// ---------------------------------------------------------------- icons
const P: Record<string, string> = {
  home: "M3 10.5 12 3l9 7.5V21h-6v-6H9v6H3z",
  wand: "M5 19 19 5M15 4l1-2 1 2 2 1-2 1-1 2-1-2-2-1zM6 6l.7-1.4L8 4l-1.3-.6L6 2l-.7 1.4L4 4l1.3.6z",
  film: "M4 4h16v16H4zM8 4v16M16 4v16M4 8h4M4 12h4M4 16h4M16 8h4M16 12h4M16 16h4",
  folder: "M3 6h6l2 2h10v11H3z",
  export: "M12 3v12M7 8l5-5 5 5M4 15v5h16v-5",
  gear: "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.4 13a7.5 7.5 0 0 0 0-2l2-1.5-2-3.4-2.3.9a7.5 7.5 0 0 0-1.7-1L15 3.5h-4l-.4 2.5a7.5 7.5 0 0 0-1.7 1l-2.3-.9-2 3.4 2 1.5a7.5 7.5 0 0 0 0 2l-2 1.5 2 3.4 2.3-.9a7.5 7.5 0 0 0 1.7 1l.4 2.5h4l.4-2.5a7.5 7.5 0 0 0 1.7-1l2.3.9 2-3.4z",
  plus: "M12 5v14M5 12h14",
  upload: "M12 16V4M7 9l5-5 5 5M4 20h16",
  play: "M7 4v16l13-8z",
  pause: "M7 4h4v16H7zM13 4h4v16h-4z",
  start: "M6 4v16M20 4 9 12l11 8z",
  end: "M18 4v16M4 4l11 8-11 8z",
  prev: "M14 6l-6 6 6 6",
  next: "M10 6l6 6-6 6",
  undo: "M9 14 4 9l5-5M4 9h10a6 6 0 0 1 0 12h-3",
  redo: "M15 14l5-5-5-5M20 9H10a6 6 0 0 0 0 12h3",
  scissors: "M6 9a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM6 21a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM8.1 8.1 20 20M8.1 15.9 20 4",
  trash: "M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13",
  ripple: "M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13M10 12l-2 2 2 2",
  copy: "M8 8h12v12H8zM4 16V4h12",
  magnet: "M6 3v9a6 6 0 0 0 12 0V3h-4v9a2 2 0 0 1-4 0V3zM6 7h4M14 7h4",
  eye: "M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12zM12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z",
  eyeoff: "M3 3l18 18M10.6 5.1A10 10 0 0 1 12 5c6 0 10 7 10 7a17 17 0 0 1-3 3.7M6.6 6.6C3.8 8.4 2 12 2 12s4 7 10 7a9.6 9.6 0 0 0 4.4-1.1",
  vol: "M4 9h4l5-4v14l-5-4H4zM16 9a4 4 0 0 1 0 6",
  mute: "M4 9h4l5-4v14l-5-4H4zM17 9l5 6M22 9l-5 6",
  lock: "M6 11h12v10H6zM8 11V7a4 4 0 0 1 8 0v4",
  unlock: "M6 11h12v10H6zM8 11V7a4 4 0 0 1 7.5-2",
  zoomin: "M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14zM21 21l-5-5M11 8v6M8 11h6",
  zoomout: "M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14zM21 21l-5-5M8 11h6",
  x: "M6 6l12 12M18 6 6 18",
  retry: "M20 11a8 8 0 1 0-2.3 5.7M20 4v7h-7",
  check: "M5 12l5 5L20 7",
  warn: "M12 3 2 20h20zM12 10v4M12 17v.5",
  music: "M9 18V5l11-2v13M9 18a3 3 0 1 1-6 0 3 3 0 0 1 6 0zM20 16a3 3 0 1 1-6 0 3 3 0 0 1 6 0z",
  image: "M3 5h18v14H3zM3 16l5-5 4 4 3-3 6 6M15.5 9a1.5 1.5 0 1 0 0-.01",
  fit: "M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5",
};

export function Icon({ name, size = 16 }: { name: string; size?: number }) {
  return (
    <svg className="ico" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={P[name] ?? ""} />
    </svg>
  );
}

// ---------------------------------------------------------------- toasts
type Toast = { id: number; text: string; err?: boolean };
const ToastCtx = createContext<(text: string, err?: boolean) => void>(() => {});
export const useToast = () => useContext(ToastCtx);

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const push = useCallback((text: string, err?: boolean) => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t.slice(-3), { id, text, err }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), err ? 5000 : 2600);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="toast-wrap" role="status">
        {toasts.map((t) => <div key={t.id} className={"toast" + (t.err ? " err" : "")}>{t.text}</div>)}
      </div>
    </ToastCtx.Provider>
  );
}

// ---------------------------------------------------------------- modal prompt
export function PromptModal({ title, label, initial = "", confirm = "Create", onSubmit, onClose }: {
  title: string; label: string; initial?: string; confirm?: string;
  onSubmit: (v: string) => void; onClose: () => void;
}) {
  const [v, setV] = useState(initial);
  const ref = useRef<HTMLInputElement>(null);
  useEffect(() => { ref.current?.focus(); ref.current?.select(); }, []);
  return (
    <div className="modal-bg" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <form className="modal" onSubmit={(e) => { e.preventDefault(); if (v.trim()) onSubmit(v.trim()); }}>
        <h2>{title}</h2>
        <label className="field">{label}
          <input ref={ref} type="text" value={v} maxLength={120} onChange={(e) => setV(e.target.value)}
            onKeyDown={(e) => e.key === "Escape" && onClose()} />
        </label>
        <div className="row"><span className="spacer" />
          <button type="button" className="btn" onClick={onClose}>Cancel</button>
          <button className="btn primary" disabled={!v.trim()}>{confirm}</button>
        </div>
      </form>
    </div>
  );
}

// ---------------------------------------------------------------- jobs
export function useJobs(projectId?: string, enabled = true) {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [tick, setTick] = useState(0);
  const refresh = useCallback(() => setTick((t) => t + 1), []);
  useEffect(() => {
    if (!enabled) return;
    let alive = true;
    let timer: any;
    const load = async () => {
      try {
        const j = await api.jobs(projectId);
        if (!alive) return;
        setJobs(j);
        const active = j.some((x) => x.status === "queued" || x.status === "running");
        timer = setTimeout(load, active ? 700 : 4000);
      } catch { timer = setTimeout(load, 4000); }
    };
    load();
    return () => { alive = false; clearTimeout(timer); };
  }, [projectId, enabled, tick]);
  return { jobs, refresh };
}

const KIND_LABEL: Record<string, string> = { derive_media: "Prepare media", render: "Export", analyze: "Analyse recording", thumb_analyze: "Analyse edit for thumbnail", thumb_generate: "Generate artwork" };

export function statusChip(s: Job["status"]) {
  const cls = s === "succeeded" ? "ok" : s === "running" || s === "queued" ? "run" : s === "cancelled" ? "" : "err";
  return <span className={"chip " + cls}>{s}</span>;
}

export function JobRow({ job, onChange, compact }: { job: Job; onChange?: () => void; compact?: boolean }) {
  const toast = useToast();
  const active = job.status === "running" || job.status === "queued";
  const [open, setOpen] = useState(false);
  const pct = job.progress != null ? Math.round(job.progress * 100) : null;
  return (
    <div style={{ display: "grid", gap: 6, padding: "10px 0", borderBottom: "1px solid var(--line)" }}>
      <div className="row">
        <strong style={{ fontSize: 12 }}>{KIND_LABEL[job.kind] ?? job.kind}</strong>
        {job.kind === "render" && job.params.filename && <span className="muted ellipsis">{job.params.filename}</span>}
        <span className="spacer" />
        {statusChip(job.status)}
        {active && <button className="btn sm ghost" title="Cancel" onClick={async () => { await api.cancelJob(job.id); onChange?.(); }}><Icon name="x" size={14} /></button>}
        {["failed", "cancelled", "interrupted"].includes(job.status) && !compact &&
          <button className="btn sm ghost" title="Retry" onClick={async () => {
            try { await api.retryJob(job.id); onChange?.(); } catch (e: any) { toast(e.message, true); }
          }}><Icon name="retry" size={14} /></button>}
      </div>
      {active && (
        <>
          <div className={"bar" + (pct == null ? " indeterminate" : "")}><div style={{ width: `${pct ?? 0}%` }} /></div>
          <div className="row muted" style={{ fontSize: 11 }}>
            <span>{job.stage}{job.stage_count > 1 ? ` · step ${job.stage_index}/${job.stage_count}` : ""}</span>
            <span className="spacer" />
            {pct != null ? <span className="mono">{pct}%</span> : <span>progress not measurable for this step</span>}
          </div>
        </>
      )}
      {job.error && (
        <div style={{ fontSize: 12, color: "var(--err)" }}>
          {job.error}{" "}
          {job.error_detail && <button className="btn sm ghost" onClick={() => setOpen(!open)}>{open ? "Hide" : "Details"}</button>}
          {open && <pre className="err">{job.error_detail}</pre>}
        </div>
      )}
    </div>
  );
}
