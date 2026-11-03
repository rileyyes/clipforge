import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError } from "../api";
import Inspector from "../components/Inspector";
import EffectsPanel, { FX_COLOR } from "../components/EffectsPanel";
import HistoryPanel from "../components/HistoryPanel";
import { effectTime } from "../timeline/effects";
import MediaLibrary from "../components/MediaLibrary";
import Monitor from "../components/Monitor";
import TimelineView from "../components/TimelineView";
import { Icon, useJobs, useToast } from "../components/ui";
import { History } from "../timeline/history";
import {
  addMedia, addTrack, deleteClips, duplicateClip, findClip, moveClip, removeTrack, sanitize, setFades, setTrackRole,
  setTransition, splitAt, timelineDuration, toggleTrack, trimEdge, updateClip, type ClipPatch, type OpResult,
} from "../timeline/ops";
import type { AudioSettings, CaptionSettings, Effect, MediaMap, Project, Timeline } from "../timeline/types";

type Doc = { timeline: Timeline; effects: Effect[]; captions: CaptionSettings; audio: AudioSettings };
import { go } from "../router";

type SaveState = "saved" | "pending" | "saving" | "error" | "conflict";

export default function Editor({ projectId }: { projectId: string }) {
  const [project, setProject] = useState<Project | null>(null);
  const [timeline, setTimeline] = useState<Timeline | null>(null);
  const [effects, setEffects] = useState<Effect[]>([]);
  const [captions, setCaptions] = useState<CaptionSettings | null>(null);
  const [audio, setAudioState] = useState<AudioSettings | null>(null);
  const [rightTab, setRightTab] = useState<"clip" | "fx" | "history">("clip");
  const [selection, setSelection] = useState<string[]>([]);
  const [playhead, setPlayhead] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [pps, setPps] = useState(40);
  const [snapping, setSnapping] = useState(true);
  const [save, setSave] = useState<SaveState>("saved");
  const [saveError, setSaveError] = useState("");
  const [loadError, setLoadError] = useState("");
  const [tlHeight, setTlHeight] = useState(() => Math.round(window.innerHeight * 0.38));
  const [, force] = useState(0);
  const history = useRef(new History<Doc>());
  const lastLabel = useRef<{ label: string; at: number }>({ label: "", at: 0 });
  const editRev = useRef(0);
  const dirty = useRef(false);
  const saving = useRef(false);
  const latest = useRef<{ timeline: Timeline | null; project: Project | null; effects: Effect[]; captions: CaptionSettings | null; audio: AudioSettings | null }>({ timeline: null, project: null, effects: [], captions: null, audio: null });
  latest.current = { timeline, project, effects, captions, audio };
  const toast = useToast();
  const { jobs, refresh: refreshJobs } = useJobs(projectId);

  // ---------------------------------------------------------------- load
  const reloadMedia = useCallback(async () => {
    const p = await api.project(projectId);
    setProject((cur) => (cur ? { ...cur, media: p.media, missing_media: p.missing_media, revision: p.revision } : p));
  }, [projectId]);

  useEffect(() => {
    localStorage.setItem("cf:lastProject", projectId);
    api.project(projectId).then((p) => {
      setProject(p); setTimeline(p.timeline); setEffects(p.effects ?? []); setCaptions(p.captions); setAudioState(p.audio); editRev.current = p.edit_revision;
      // zoom so the edit roughly fits
      const d = timelineDuration(p.timeline);
      if (d > 0) setPps(Math.max(2, Math.min(200, (window.innerWidth - 220) / (d * 1.15))));
    }).catch((e) => setLoadError(e instanceof ApiError && e.status === 404 ? "This project doesn't exist (it may have been deleted)." : e.message));
  }, [projectId]);

  // derived media (thumbnails/waveforms/proxies) finish in the background → refresh
  const doneDerives = jobs.filter((j) => j.kind === "derive_media" && j.status === "succeeded").length;
  useEffect(() => { if (project) reloadMedia(); }, [doneDerives]);

  const media: MediaMap = useMemo(() => Object.fromEntries((project?.media ?? []).map((m) => [m.id, m])), [project?.media]);

  // ---------------------------------------------------------------- autosave
  const flush = useCallback(async () => {
    if (saving.current || !dirty.current) return;
    const { timeline: tl, project: p, effects: fxs, captions: caps, audio: aud } = latest.current;
    if (!tl || !p) return;
    saving.current = true; dirty.current = false; setSave("saving");
    try {
      const saved = await api.saveTimeline(projectId, editRev.current, tl, p.output, fxs, caps ?? undefined, aud ?? undefined);
      editRev.current = saved.edit_revision;
      setProject((cur) => (cur ? { ...cur, media: saved.media, revision: saved.revision, updated_at: saved.updated_at } : saved));
      setSave(dirty.current ? "pending" : "saved");
    } catch (e: any) {
      if (e instanceof ApiError && e.status === 409) { setSave("conflict"); }
      else { setSave("error"); setSaveError(e.message); dirty.current = true; }
    } finally {
      saving.current = false;
      if (dirty.current) setTimeout(flush, 300);
    }
  }, [projectId]);

  useEffect(() => {
    if (!dirty.current) return;
    setSave("pending");
    const t = setTimeout(flush, 700);
    return () => clearTimeout(t);
  }, [timeline, effects, captions, audio]);

  useEffect(() => {
    const warn = (e: BeforeUnloadEvent) => { if (dirty.current || saving.current) { e.preventDefault(); } };
    window.addEventListener("beforeunload", warn);
    return () => { window.removeEventListener("beforeunload", warn); if (dirty.current) flush(); };
  }, [flush]);

  // ---------------------------------------------------------------- editing
  function snapshot(): Doc {
    const l = latest.current;
    return { timeline: l.timeline!, effects: l.effects, captions: l.captions!, audio: l.audio! };
  }

  const commit = useCallback((r: OpResult, label: string) => {
    if (r.error !== undefined) { toast(r.error, true); return false; }
    const cur = latest.current.timeline!;
    if (r.timeline === cur) return true;
    history.current.push(snapshot(), label);
    dirty.current = true;
    setTimeline(sanitize(r.timeline));
    if (r.created?.length && label !== "Split") setSelection([r.created[0]]);
    return true;
  }, [toast]);

  const restore = (d: Doc) => { dirty.current = true; setTimeline(d.timeline); setEffects(d.effects); setCaptions(d.captions); setAudioState(d.audio); };
  const undo = () => {
    const e = history.current.undo(snapshot());
    if (!e) return;
    restore(e.state); toast(`Undo: ${e.label}`);
  };
  const redo = () => {
    const e = history.current.redo(snapshot());
    if (!e) return;
    restore(e.state); toast(`Redo: ${e.label}`);
  };
  /** Save pending edits now (used before snapshots and restores). */
  const flushNow = async () => {
    for (let i = 0; i < 50 && saving.current; i++) await new Promise((r) => setTimeout(r, 100));
    if (dirty.current) await flush();
  };
  const onRestored = (p: Project) => {
    dirty.current = false;
    history.current.clear();
    editRev.current = p.edit_revision;
    setProject(p); setTimeline(p.timeline); setEffects(p.effects ?? []); setCaptions(p.captions); setAudioState(p.audio);
    setSelection([]); setSave("saved");
  };
  /** Effects/captions edits share the timeline's undo history; rapid slider moves coalesce. */
  const setFx = (next: Effect[], caps: CaptionSettings, label: string) => {
    const now = Date.now();
    if (!(lastLabel.current.label === label && now - lastLabel.current.at < 800)) history.current.push(snapshot(), label);
    lastLabel.current = { label, at: now };
    dirty.current = true; setEffects(next); setCaptions(caps); force((n) => n + 1);
  };
  const setAudio = (next: AudioSettings, label: string) => {
    const now = Date.now();
    if (!(lastLabel.current.label === label && now - lastLabel.current.at < 800)) history.current.push(snapshot(), label);
    lastLabel.current = { label, at: now };
    dirty.current = true; setAudioState(next); force((n) => n + 1);
  };

  const seek = useCallback((t: number) => setPlayhead(Math.max(0, t)), []);
  /** Split targets: selected clips under the playhead, else every unlocked clip under it. */
  const splitTargets = (): string[] => {
    const under = (c: { start: number; source_in: number; source_out: number; speed: number }) =>
      playhead > c.start + 1e-6 && playhead < c.start + (c.source_out - c.source_in) / c.speed - 1e-6;
    const sel = selection.filter((id) => { const r = findClip(timeline!, id); return r && under(r.clip); });
    if (sel.length) return sel;
    return timeline!.tracks.filter((t) => !t.locked).flatMap((t) => t.clips.filter(under).map((c) => c.id));
  };

  const actions = {
    split: () => {
      const ids = splitTargets();
      if (!ids.length) return toast("Move the playhead over a clip to split it", true);
      commit(splitAt(timeline!, ids, playhead), "Split");
    },
    del: (ripple: boolean) => {
      if (!selection.length) return toast("Select a clip first", true);
      if (commit(deleteClips(timeline!, selection, ripple), ripple ? "Ripple delete" : "Delete")) setSelection([]);
    },
    duplicate: () => {
      if (selection.length !== 1) return toast("Select one clip to duplicate", true);
      commit(duplicateClip(timeline!, selection[0]), "Duplicate");
    },
  };

  // ---------------------------------------------------------------- keyboard
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement;
      if (el.closest("input, select, textarea")) return;
      const mod = e.ctrlKey || e.metaKey;
      const k = e.key.toLowerCase();
      if (k === " ") { e.preventDefault(); setPlaying((p) => !p); }
      else if (mod && k === "z") { e.preventDefault(); e.shiftKey ? redo() : undo(); }
      else if (mod && k === "y") { e.preventDefault(); redo(); }
      else if (mod && k === "d") { e.preventDefault(); actions.duplicate(); }
      else if (mod && k === "s") { e.preventDefault(); dirty.current = true; flush(); }
      else if (k === "s" && !mod) actions.split();
      else if (k === "delete" || k === "backspace") { e.preventDefault(); actions.del(e.shiftKey); }
      else if (k === "n" && !mod) setSnapping((s) => !s);
      else if (k === "arrowleft") { setPlaying(false); seek(playhead - 1 / (project?.output.fps ?? 30)); }
      else if (k === "arrowright") { setPlaying(false); seek(playhead + 1 / (project?.output.fps ?? 30)); }
      else if (k === "home") seek(0);
      else if (k === "end") seek(timelineDuration(timeline!));
      else if (k === "escape") setSelection([]);
      else return;
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  // ---------------------------------------------------------------- resize splitter
  const startResize = (e: React.PointerEvent) => {
    const y0 = e.clientY, h0 = tlHeight;
    const mv = (ev: PointerEvent) => setTlHeight(Math.max(140, Math.min(window.innerHeight - 260, h0 - (ev.clientY - y0))));
    window.addEventListener("pointermove", mv);
    window.addEventListener("pointerup", () => window.removeEventListener("pointermove", mv), { once: true });
  };

  if (loadError) return <div className="page"><h1>Can't open project</h1><p className="muted">{loadError}</p><a href="#/projects">Back to projects</a></div>;
  if (!project || !timeline) return <div className="page muted">Loading project…</div>;

  const usedIds = new Set(timeline.tracks.flatMap((t) => t.clips.map((c) => c.media_id)));
  const missing = project.missing_media?.length ?? 0;

  const toolbar = (
    <>
      <button className="btn icon ghost" title={`Undo${history.current.undoLabel ? ": " + history.current.undoLabel : ""} (Ctrl+Z)`} disabled={!history.current.canUndo} onClick={undo}><Icon name="undo" /></button>
      <button className="btn icon ghost" title={`Redo${history.current.redoLabel ? ": " + history.current.redoLabel : ""} (Ctrl+Shift+Z)`} disabled={!history.current.canRedo} onClick={redo}><Icon name="redo" /></button>
      <span style={{ width: 1, height: 20, background: "var(--line)" }} />
      <button className="btn sm ghost" title="Split at playhead (S)" onClick={actions.split}><Icon name="scissors" size={14} />Split</button>
      <button className="btn sm ghost" title="Delete (Del)" disabled={!selection.length} onClick={() => actions.del(false)}><Icon name="trash" size={14} />Delete</button>
      <button className="btn sm ghost" title="Delete and close the gap (Shift+Del)" disabled={!selection.length} onClick={() => actions.del(true)}><Icon name="ripple" size={14} />Ripple delete</button>
      <button className="btn sm ghost" title="Duplicate (Ctrl+D)" disabled={selection.length !== 1} onClick={actions.duplicate}><Icon name="copy" size={14} />Duplicate</button>
      <button className={"btn sm" + (snapping ? " on" : " ghost")} title="Snapping (N) — hold Alt while dragging to bypass" onClick={() => setSnapping(!snapping)}><Icon name="magnet" size={14} />Snap</button>
      <span style={{ width: 1, height: 20, background: "var(--line)" }} />
      <button className="btn sm ghost" onClick={() => commit(addTrack(timeline, "video"), "Add video track")}><Icon name="plus" size={14} />Video track</button>
      <button className="btn sm ghost" onClick={() => commit(addTrack(timeline, "audio"), "Add audio track")}><Icon name="plus" size={14} />Audio track</button>
      <span className="spacer" />
      <button className="btn icon ghost" title="Zoom out" onClick={() => setPps(Math.max(2, pps / 1.4))}><Icon name="zoomout" size={15} /></button>
      <input type="range" min={0} max={1} step={0.001} style={{ width: 110 }} title="Zoom (Ctrl + mouse wheel)"
        value={Math.log(pps / 2) / Math.log(400)} onChange={(e) => setPps(2 * Math.pow(400, +e.target.value))} />
      <button className="btn icon ghost" title="Zoom in" onClick={() => setPps(Math.min(800, pps * 1.4))}><Icon name="zoomin" size={15} /></button>
      <button className="btn icon ghost" title="Fit timeline" onClick={() => { const d = timelineDuration(timeline); if (d > 0) setPps(Math.max(2, Math.min(800, (window.innerWidth - 240) / (d * 1.08)))); }}><Icon name="fit" size={15} /></button>
    </>
  );

  return (
    <div className="editor" style={{ ["--tl-h" as any]: `${tlHeight}px` }}>
      <div className="ed-top">
        <input className="ed-title" defaultValue={project.name} aria-label="Project name"
          onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
          onBlur={async (e) => {
            const v = e.target.value.trim();
            if (!v || v === project.name) { e.target.value = project.name; return; }
            try { const p = await api.rename(projectId, v); setProject((c) => (c ? { ...c, name: p.name } : c)); }
            catch (err: any) { toast(err.message, true); e.target.value = project.name; }
          }} />
        <span className="save-state">
          <span className={"dot" + (save === "saved" ? "" : save === "error" || save === "conflict" ? " bad" : " busy")} />
          {{ saved: "All changes saved", pending: "Unsaved changes…", saving: "Saving…", error: "Save failed — retrying", conflict: "Changed elsewhere" }[save]}
        </span>
        {missing > 0 && <span className="chip err">{missing} media file(s) missing</span>}
        <span className="spacer" />
        {jobs.filter((j) => j.kind === "render" && (j.status === "running" || j.status === "queued")).map((j) => (
          <span key={j.id} className="chip run">Exporting {j.progress != null ? `${Math.round(j.progress * 100)}%` : "…"}</span>
        ))}
        <button className="btn primary" onClick={() => { dirty.current = true; flush().then(() => go(`export/${projectId}`)); }}>
          <Icon name="export" />Export
        </button>
      </div>
      {save === "conflict" && (
        <div className="banner err" style={{ position: "absolute", top: 46, left: 56, right: 0, zIndex: 20 }}>
          This project was changed in another window or tab. Your latest edits here were not saved.
          <button className="btn sm" onClick={() => window.location.reload()}>Reload project</button>
        </div>
      )}
      {save === "error" && saveError && (
        <div className="banner" style={{ position: "absolute", top: 46, left: 56, right: 0, zIndex: 20 }}>{saveError}</div>
      )}
      <div className="ed-mid">
        <MediaLibrary project={project} jobs={jobs} usedIds={usedIds}
          onAdd={(m) => commit(addMedia(timeline, m), "Add clip")}
          onChanged={() => { reloadMedia(); refreshJobs(); }} />
        <Monitor projectId={projectId} timeline={timeline} media={media} output={project.output} effects={effects}
          playhead={playhead} setPlayhead={setPlayhead} playing={playing} setPlaying={setPlaying} />
        <div className="pane">
          <div className="pane-head" style={{ gap: 4 }}>
            <button className={"btn sm" + (rightTab === "clip" ? " on" : " ghost")} onClick={() => setRightTab("clip")}>Clip</button>
            <button className={"btn sm" + (rightTab === "fx" ? " on" : " ghost")} onClick={() => setRightTab("fx")}><Icon name="wand" size={13} />Effects{effects.length ? ` (${effects.length})` : ""}</button>
            <button className={"btn sm" + (rightTab === "history" ? " on" : " ghost")} onClick={() => setRightTab("history")}><Icon name="undo" size={13} />History</button>
          </div>
          {rightTab === "history" ? (
            <HistoryPanel projectId={projectId} beforeChange={flushNow} onRestored={onRestored} revision={editRev.current} />
          ) : rightTab === "clip" ? (
            <Inspector timeline={timeline} media={media} selection={selection}
              onPatch={(id, patch: ClipPatch, label) => commit(updateClip(timeline, id, patch), label)}
              onTrim={(id, edge, t) => commit(trimEdge(timeline, id, edge, t, media), "Trim clip")}
              onMove={(id, s) => commit(moveClip(timeline, id, s), "Move clip")}
              onTransition={(id, tr) => commit(setTransition(timeline, id, tr), tr ? "Set transition" : "Remove transition")}
              onFades={(id, a, b) => commit(setFades(timeline, id, a, b), "Fades")} />
          ) : captions && audio && (
            <EffectsPanel projectId={projectId} timeline={timeline} effects={effects} captions={captions} playhead={playhead}
              audio={audio} setAudio={setAudio}
              jobs={jobs} onJobs={refreshJobs} setFx={setFx} seek={(t) => { setPlaying(false); seek(t); }} />
          )}
        </div>
      </div>
      <div className="splitter" onPointerDown={startResize} />
      <TimelineView projectId={projectId} timeline={timeline} media={media} selection={selection} setSelection={setSelection}
        playhead={playhead} seek={(t) => { seek(t); }} playing={playing} pps={pps} setPps={setPps} snapping={snapping}
        commit={(r, l) => { commit(r, l); force((n) => n + 1); }}
        onDropMedia={(mid, time, trackId) => {
          const m = media[mid];
          if (!m) return;
          const tr = timeline.tracks.find((t) => t.id === trackId);
          commit(addMedia(timeline, m, time, tr?.kind === "video" ? trackId : undefined), "Add clip");
        }}
        onTrackToggle={(id, flag) => commit(toggleTrack(timeline, id, flag), `Toggle ${flag}`)}
        onTrackRole={(id, role) => commit(setTrackRole(timeline, id, role), role === "music" ? "Set music track" : "Set dialogue track")}
        onRemoveTrack={(id) => commit(removeTrack(timeline, id), "Remove track")}
        markers={effects.filter((e) => e.enabled).map((e) => ({ t: effectTime(timeline, e), color: FX_COLOR[e.kind], title: e.kind + (e.word ? `: ${e.word}` : e.text ? `: ${e.text}` : "") })).filter((m) => m.t !== null) as any}
        toolbar={toolbar} />
    </div>
  );
}
