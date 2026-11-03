import React, { useEffect, useState } from "react";
import { fmtTime, versions, type Comparison, type VersionMeta } from "../api";
import { Icon, PromptModal, useToast } from "./ui";

const ORIGIN: Record<VersionMeta["origin"], [string, string]> = {
  manual: ["Saved", "ok"],
  auto: ["Autosave", ""],
  before_ai: ["Before AI edit", "run"],
  before_restore: ["Before restore", "run"],
  imported: ["Imported", ""],
};

function when(iso: string): string {
  const d = new Date(iso);
  const s = (Date.now() - d.getTime()) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

/** Version history: save named versions, restore any version, compare two versions. */
export default function HistoryPanel({ projectId, beforeChange, onRestored, revision }: {
  projectId: string;
  /** Flush unsaved edits so snapshots/restores see the latest state. */
  beforeChange: () => Promise<void>;
  onRestored: (p: import("../timeline/types").Project) => void;
  /** Changes whenever the project is saved, so the list refreshes. */
  revision: number;
}) {
  const [list, setList] = useState<VersionMeta[] | null>(null);
  const [naming, setNaming] = useState<null | { id?: string; initial: string }>(null);
  const [cmp, setCmp] = useState<null | { a: string; b: string }>(null);
  const [busy, setBusy] = useState(false);
  const toast = useToast();

  const load = () => versions.list(projectId).then(setList).catch((e) => toast(e.message, true));
  useEffect(() => { load(); }, [projectId, revision]);

  const save = async (label: string) => {
    setNaming(null);
    try { await beforeChange(); await versions.save(projectId, label); toast(`Saved version “${label}”`); load(); }
    catch (e: any) { toast(e.message, true); }
  };
  const rename = async (id: string, label: string) => {
    setNaming(null);
    try { await versions.rename(projectId, id, label); load(); } catch (e: any) { toast(e.message, true); }
  };
  const restore = async (v: VersionMeta) => {
    if (!confirm(`Restore “${v.label}”? Your current edit is saved as a version first, so you can switch back.`)) return;
    setBusy(true);
    try {
      await beforeChange();
      const p = await versions.restore(projectId, v.id);
      onRestored(p);
      toast(`Restored “${v.label}”`);
      load();
    } catch (e: any) { toast(e.message, true); } finally { setBusy(false); }
  };
  const remove = async (v: VersionMeta) => {
    if (!confirm(`Delete the version “${v.label}”? This can't be undone.`)) return;
    try { await versions.remove(projectId, v.id); load(); } catch (e: any) { toast(e.message, true); }
  };

  if (cmp) return <CompareView projectId={projectId} list={list ?? []} init={cmp} onClose={() => setCmp(null)} />;

  return (
    <div className="pane-body grid hist-body" style={{ gap: 10, alignContent: "start" }} data-testid="history-panel">
      <button className="btn primary" onClick={() => setNaming({ initial: `Version ${new Date().toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}` })}>
        <Icon name="plus" size={14} />Save this version
      </button>
      <div className="muted" style={{ fontSize: 11 }}>
        Versions are also saved automatically every 10 minutes while you edit, and before every AI edit or restore.
      </div>
      {list === null && <div className="muted">Loading…</div>}
      {list?.length === 0 && <div className="muted" style={{ fontSize: 12 }}>No versions yet.</div>}
      {list?.map((v) => (
        <div key={v.id} className="version-row" data-testid="version">
          <div className="row" style={{ gap: 6 }}>
            <strong className="ellipsis" style={{ fontSize: 12 }} title={v.label}>{v.label}</strong>
            <span className="spacer" />
            <span className={"chip " + ORIGIN[v.origin][1]}>{ORIGIN[v.origin][0]}</span>
          </div>
          <div className="muted" style={{ fontSize: 11 }}>
            {when(v.created_at)} · {fmtTime(v.duration, false)} · {v.clips} clip{v.clips === 1 ? "" : "s"}{v.effects ? ` · ${v.effects} effect${v.effects === 1 ? "" : "s"}` : ""}
          </div>
          <div className="row" style={{ gap: 2 }}>
            <button className="btn sm" disabled={busy} onClick={() => restore(v)}><Icon name="undo" size={13} />Restore</button>
            <button className="btn sm ghost" onClick={async () => {
              // "current" is read from the server, so save pending edits first
              try { await beforeChange(); } catch { /* compare what's saved */ }
              setCmp({ a: v.id, b: "current" });
            }}>Compare</button>
            <span className="spacer" />
            <button className="btn icon ghost" title="Rename" onClick={() => setNaming({ id: v.id, initial: v.label })}><Icon name="pencil" size={13} /></button>
            <button className="btn icon ghost" title="Delete version" onClick={() => remove(v)}><Icon name="trash" size={13} /></button>
          </div>
        </div>
      ))}
      {naming && (
        <PromptModal title={naming.id ? "Rename version" : "Save version"} label="Name" initial={naming.initial}
          confirm={naming.id ? "Rename" : "Save"} onClose={() => setNaming(null)}
          onSubmit={(v) => (naming.id ? rename(naming.id, v.slice(0, 80)) : save(v.slice(0, 80)))} />
      )}
    </div>
  );
}

// ---------------------------------------------------------------- compare
function Bar({ ranges, dur, color, extra }: { ranges: [number, number][]; dur: number; color: string; extra?: { ranges: [number, number][]; color: string } }) {
  const seg = (r: [number, number], c: string, k: string) => (
    <div key={k} style={{ position: "absolute", top: 0, bottom: 0, left: `${(r[0] / dur) * 100}%`, width: `${Math.max(0.3, ((r[1] - r[0]) / dur) * 100)}%`, background: c }} />
  );
  return (
    <div style={{ position: "relative", height: 12, background: "var(--panel-2)", borderRadius: 3, overflow: "hidden" }}>
      {ranges.map((r, i) => seg(r, color, "r" + i))}
      {extra?.ranges.map((r, i) => seg(r, extra.color, "x" + i))}
    </div>
  );
}

const fmtVal = (v: unknown) => (v === null || v === undefined ? "—" : typeof v === "boolean" ? (v ? "on" : "off") : String(v));
const kindList = (o: Record<string, number>) => Object.entries(o).map(([k, n]) => `${n} ${k}`).join(", ");

function CompareView({ projectId, list, init, onClose }: { projectId: string; list: VersionMeta[]; init: { a: string; b: string }; onClose: () => void }) {
  const [a, setA] = useState(init.a);
  const [b, setB] = useState(init.b);
  const [r, setR] = useState<Comparison | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    setR(null); setError("");
    versions.compare(projectId, a, b).then(setR).catch((e) => setError(e.message));
  }, [a, b]);
  const opts = [<option key="current" value="current">Current edit</option>,
    ...list.map((v) => <option key={v.id} value={v.id}>{v.label} ({when(v.created_at)})</option>)];
  return (
    <div className="pane-body grid hist-body" style={{ gap: 10, alignContent: "start" }} data-testid="compare-view">
      <div className="row"><strong>Compare versions</strong><span className="spacer" /><button className="btn sm ghost" onClick={onClose}><Icon name="x" size={13} />Close</button></div>
      <label className="field">A (older)<select value={a} onChange={(e) => setA(e.target.value)}>{opts}</select></label>
      <label className="field">B (newer)<select value={b} onChange={(e) => setB(e.target.value)}>{opts}</select></label>
      {error && <div className="chip err">{error}</div>}
      {!r && !error && <div className="muted">Comparing…</div>}
      {r && (
        <>
          {r.identical && <div className="chip ok">These two versions are identical.</div>}
          <table className="cmp-table">
            <thead><tr><th /><th>A</th><th>B</th></tr></thead>
            <tbody>
              <tr><td>Length</td><td className="mono">{fmtTime(r.a.duration, false)}</td><td className="mono">{fmtTime(r.b.duration, false)}</td></tr>
              <tr><td>Clips</td><td>{r.a.clips}</td><td>{r.b.clips}</td></tr>
              <tr><td>Effects</td><td>{r.a.effects}</td><td>{r.b.effects}</td></tr>
              <tr><td>Transitions</td><td>{r.a.transitions}</td><td>{r.b.transitions}</td></tr>
            </tbody>
          </table>
          {r.sources.map((s) => {
            const dur = s.duration || Math.max(1, ...[...s.a, ...s.b].map((x) => x[1]));
            return (
              <div key={s.media_id} className="grid" style={{ gap: 4 }} data-testid="cmp-source">
                <div className="ellipsis" style={{ fontSize: 12, fontWeight: 600 }} title={s.name}>{s.name}</div>
                <div className="muted" style={{ fontSize: 10 }}>Parts of the recording used — A</div>
                <Bar ranges={s.a} dur={dur} color="var(--dim)" extra={{ ranges: s.removed, color: "var(--err)" }} />
                <div className="muted" style={{ fontSize: 10 }}>B</div>
                <Bar ranges={s.b} dur={dur} color="var(--dim)" extra={{ ranges: s.added, color: "var(--ok)" }} />
                <div style={{ fontSize: 11 }}>
                  {s.removed_s > 0 && <span style={{ color: "var(--err)" }}>−{s.removed_s.toFixed(1)}s cut ({s.removed.length} part{s.removed.length === 1 ? "" : "s"}) </span>}
                  {s.added_s > 0 && <span style={{ color: "var(--ok)" }}>+{s.added_s.toFixed(1)}s added ({s.added.length} part{s.added.length === 1 ? "" : "s"})</span>}
                  {!s.removed_s && !s.added_s && <span className="muted">same footage</span>}
                </div>
              </div>
            );
          })}
          {(Object.keys(r.effects.added).length > 0 || Object.keys(r.effects.removed).length > 0 || r.effects.changed > 0) && (
            <div style={{ fontSize: 12 }}>
              <strong>Effects</strong>
              {Object.keys(r.effects.added).length > 0 && <div style={{ color: "var(--ok)" }}>+ {kindList(r.effects.added)}</div>}
              {Object.keys(r.effects.removed).length > 0 && <div style={{ color: "var(--err)" }}>− {kindList(r.effects.removed)}</div>}
              {r.effects.changed > 0 && <div className="muted">{r.effects.changed} changed</div>}
            </div>
          )}
          {r.settings.length > 0 && (
            <div style={{ fontSize: 12 }}>
              <strong>Settings</strong>
              {r.settings.slice(0, 20).map((x) => (
                <div key={x.group + x.setting} className="muted">{x.group} · {x.setting.replace(/_/g, " ")}: {fmtVal(x.a)} → <span style={{ color: "var(--text)" }}>{fmtVal(x.b)}</span></div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}
