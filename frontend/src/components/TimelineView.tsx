import { TITLE_TEMPLATES } from "../timeline/ops";
import React, { memo, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { fmtTime, thumbUrl, waveformUrl } from "../api";
import {
  clipDuration, clipEnd, expandLinked, updateMarker, findClip, linkedGroup, moveClip, moveClips, snap, snapPoints, timelineDuration, trimEdge, updateBlur, updateTitle, type OpResult,
} from "../timeline/ops";
import { keyframeTimes } from "../timeline/keyframes";
import { TRANSITIONS, type Clip, type Marker, type MediaMap, type Timeline, type Track } from "../timeline/types";
import { Icon } from "./ui";

const ROW_H: Record<Track["kind"], number> = { video: 58, audio: 50 };
const RULER_H = 26;
const TICK_STEPS = [0.04, 0.1, 0.25, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600];

// ---- waveform cache (one fetch per media)
const wfCache = new Map<string, Promise<{ peaks_per_second: number; peaks: number[] } | null>>();
function getWaveform(pid: string, mid: string) {
  const key = pid + mid;
  if (!wfCache.has(key)) wfCache.set(key, fetch(waveformUrl(pid, mid)).then((r) => (r.ok ? r.json() : null)).catch(() => null));
  return wfCache.get(key)!;
}

const Waveform = memo(function Waveform({ pid, clip, width, ready }: { pid: string; clip: Clip; width: number; ready: boolean }) {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    if (!ready) return;
    let alive = true;
    getWaveform(pid, clip.media_id).then((wf) => {
      const cv = ref.current;
      if (!alive || !cv || !wf) return;
      // canvases top out around 32k px; past that the strip is stretched (still exact per peak)
      const w = Math.max(1, Math.min(16000, Math.round(width)));
      const h = cv.clientHeight || 36;
      cv.width = w; cv.height = h;
      const ctx = cv.getContext("2d")!;
      ctx.clearRect(0, 0, w, h);
      ctx.fillStyle = "rgba(220,255,240,0.75)";
      const a = clip.source_in * wf.peaks_per_second, b = clip.source_out * wf.peaks_per_second;
      const gain = Math.min(2, clip.volume);
      for (let x = 0; x < w; x++) {
        const i0 = Math.floor(a + ((b - a) * x) / w), i1 = Math.max(i0 + 1, Math.floor(a + ((b - a) * (x + 1)) / w));
        let p = 0;
        if (i1 - i0 <= 1 && (b - a) / w < 1) {
          // zoomed in past the data: interpolate between neighbouring peaks
          const f = a + ((b - a) * (x + 0.5)) / w, j = Math.floor(f), q = f - j;
          p = (wf.peaks[j] ?? 0) * (1 - q) + (wf.peaks[j + 1] ?? wf.peaks[j] ?? 0) * q;
        } else for (let i = i0; i < i1 && i < wf.peaks.length; i++) p = Math.max(p, wf.peaks[i]);
        const ph = Math.min(h, (p / 255) * h * gain);
        ctx.fillRect(x, (h - ph) / 2, 1, Math.max(1, ph));
      }
    });
    return () => { alive = false; };
  }, [pid, clip.media_id, clip.source_in, clip.source_out, clip.volume, width, ready]);
  return <canvas ref={ref} />;
});

type Drag = {
  mode: "move" | "trim-start" | "trim-end";
  id: string;
  x0: number;
  orig: Clip;
  /** several selected clips dragged together (time only; they keep their tracks) */
  group?: string[];
  moved: boolean;
  preview?: OpResult;
  snapAt?: number | null;
};

export interface TimelineProps {
  projectId: string;
  timeline: Timeline;
  media: MediaMap;
  selection: string[];
  setSelection: (s: string[]) => void;
  playhead: number;
  seek: (t: number) => void;
  playing: boolean;
  pps: number;
  setPps: (n: number) => void;
  snapping: boolean;
  commit: (r: OpResult, label: string) => void;
  onDropMedia: (mediaId: string, time: number, trackId: string) => void;
  onTrackToggle: (trackId: string, flag: "muted" | "hidden" | "locked") => void;
  onTrackRole?: (trackId: string, role: "dialogue" | "music" | "narration") => void;
  onRemoveTrack: (trackId: string) => void;
  toolbar: React.ReactNode;
  markers?: { t: number; color: string; title: string }[];
  /** Phase 19: stretches the pacing checker found too still (shown in red on the ruler) */
  slow?: { start: number; end: number }[] | null;
  /** the user's own markers (M): click selects + seeks, drag moves */
  userMarkers?: Marker[];
  markerSel?: string | null;
  onMarkerSelect?: (id: string) => void;
  /** titles + blurs lane: click selects, drag moves, edges resize */
  overlaySel?: string | null;
  onOverlaySelect?: (kind: "title" | "blur", id: string) => void;
}

const OV_H = 26;
type OvDrag = { kind: "title" | "blur"; id: string; mode: "move" | "start" | "end"; x0: number; start: number; duration: number; moved: boolean };

export default function TimelineView(p: TimelineProps) {
  const { timeline, media, pps, playhead } = p;
  const scrollRef = useRef<HTMLDivElement>(null);
  const laneRefs = useRef<Record<string, HTMLDivElement | null>>({});
  const [drag, setDrag] = useState<Drag | null>(null);
  const dragRef = useRef<Drag | null>(null);
  const [view, setView] = useState({ left: 0, width: 1000 });
  const [dropTrack, setDropTrack] = useState<string | null>(null);
  const [ov, setOv] = useState<OvDrag | null>(null);
  const [ovNow, setOvNow] = useState<{ start: number; duration: number } | null>(null);
  const [mkDrag, setMkDrag] = useState<{ id: string; t: number } | null>(null);
  const zoomAnchor = useRef<{ t: number; px: number } | null>(null);

  const shown = drag?.preview?.timeline ?? timeline;
  const duration = timelineDuration(timeline);
  const contentW = Math.max((duration + 30) * pps, view.width);

  // ---- viewport tracking
  useEffect(() => {
    const el = scrollRef.current!;
    const upd = () => setView({ left: el.scrollLeft, width: el.clientWidth });
    upd();
    el.addEventListener("scroll", upd, { passive: true });
    const ro = new ResizeObserver(upd);
    ro.observe(el);
    return () => { el.removeEventListener("scroll", upd); ro.disconnect(); };
  }, []);

  // ---- ctrl+wheel zoom anchored at cursor
  useEffect(() => {
    const el = scrollRef.current!;
    const onWheel = (e: WheelEvent) => {
      if (!(e.ctrlKey || e.metaKey)) return;
      e.preventDefault();
      const rect = el.getBoundingClientRect();
      const px = e.clientX - rect.left;
      zoomAnchor.current = { t: (el.scrollLeft + px) / pps, px };
      p.setPps(Math.max(2, Math.min(800, pps * (e.deltaY < 0 ? 1.15 : 1 / 1.15))));
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [pps]);
  useLayoutEffect(() => {
    const a = zoomAnchor.current;
    if (a && scrollRef.current) { scrollRef.current.scrollLeft = a.t * pps - a.px; zoomAnchor.current = null; }
  }, [pps]);

  // ---- keep playhead visible while playing
  useEffect(() => {
    const el = scrollRef.current;
    if (!el || !p.playing) return;
    const x = playhead * pps;
    if (x > el.scrollLeft + el.clientWidth - 40 || x < el.scrollLeft) el.scrollLeft = x - 80;
  }, [playhead, p.playing, pps]);

  const timeAt = (clientX: number) => {
    const el = scrollRef.current!;
    return Math.max(0, (clientX - el.getBoundingClientRect().left + el.scrollLeft) / pps);
  };
  const trackAt = (clientY: number, kind: Track["kind"]) => {
    for (const t of timeline.tracks) {
      const el = laneRefs.current[t.id];
      if (!el || t.kind !== kind) continue;
      const r = el.getBoundingClientRect();
      if (clientY >= r.top && clientY < r.bottom) return t.id;
    }
    return undefined;
  };

  // ---- clip drag (move / trim) with live preview
  useEffect(() => {
    if (!drag) return;
    const onMove = (e: PointerEvent) => {
      const d = dragRef.current!;
      const dx = e.clientX - d.x0;
      if (!d.moved && Math.abs(dx) < 3) {
        // ignore click jitter unless the pointer moved to another track
        if (d.mode !== "move") return;
        const ref = findClip(timeline, d.id)!;
        const tr = trackAt(e.clientY, ref.track.kind);
        if (!tr || tr === ref.track.id) return;
      }
      const dt = dx / pps;
      const exclude = d.group ? expandLinked(timeline, d.group) : new Set(linkedGroup(timeline, d.id).map((r) => r.clip.id));
      const pts = p.snapping && !e.altKey ? snapPoints(timeline, exclude, playhead) : [];
      const thr = 8 / pps;
      let preview: OpResult;
      let snapAt: number | null = null;
      if (d.mode === "move") {
        let s = d.orig.start + dt;
        const dur = clipDuration(d.orig);
        const s1 = snap(s, pts, thr), s2 = snap(s + dur, pts, thr) - dur;
        if (s1 !== s && (Math.abs(s1 - s) <= Math.abs(s2 - s) || s2 === s)) { snapAt = s1; s = s1; }
        else if (s2 !== s) { snapAt = s2 + dur; s = s2; }
        const ref = findClip(timeline, d.id)!;
        preview = d.group
          ? moveClips(timeline, d.group, s - d.orig.start)
          : moveClip(timeline, d.id, s, trackAt(e.clientY, ref.track.kind) ?? ref.track.id);
      } else {
        const base = d.mode === "trim-start" ? d.orig.start : clipEnd(d.orig);
        let t = base + dt;
        const st = snap(t, pts, thr);
        if (st !== t) { snapAt = st; t = st; }
        preview = trimEdge(timeline, d.id, d.mode === "trim-start" ? "start" : "end", t, media);
      }
      const nd = { ...d, moved: true, preview, snapAt };
      dragRef.current = nd;
      setDrag(nd);
    };
    const onUp = () => {
      const d = dragRef.current;
      dragRef.current = null;
      setDrag(null);
      if (d?.moved && d.preview) {
        p.commit(d.preview, d.mode === "move" ? (d.group ? `Move ${d.group.length} clips` : "Move clip") : "Trim clip");
      } else if (d?.group) {
        p.setSelection([d.id]); // a plain click on one of several selected clips selects just it
      }
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp, { once: true });
    return () => { window.removeEventListener("pointermove", onMove); window.removeEventListener("pointerup", onUp); };
  }, [drag !== null]);

  const startDrag = (e: React.PointerEvent, clip: Clip, mode: Drag["mode"]) => {
    if (e.button !== 0) return;
    e.stopPropagation();
    const multi = e.shiftKey || e.ctrlKey || e.metaKey;
    if (multi) {
      p.setSelection(p.selection.includes(clip.id) ? p.selection.filter((x) => x !== clip.id) : [...p.selection, clip.id]);
      return;
    }
    const group = mode === "move" && p.selection.length > 1 && p.selection.includes(clip.id) ? [...p.selection] : undefined;
    if (!group && (!p.selection.includes(clip.id) || p.selection.length > 1)) p.setSelection([clip.id]);
    const track = findClip(timeline, clip.id)!.track;
    if (track.locked) return;
    const d: Drag = { mode, id: clip.id, x0: e.clientX, orig: clip, group, moved: false };
    dragRef.current = d;
    setDrag(d);
  };

  // ---- user markers: click = select + seek, drag = move (snaps like clips; Alt bypasses)
  const startMarker = (e: React.PointerEvent, m: Marker) => {
    if (e.button !== 0) return;
    e.stopPropagation();
    p.onMarkerSelect?.(m.id);
    p.seek(m.t);
    const x0 = e.clientX;
    let moved = false, cur = m.t;
    const pts = snapPoints(timeline, new Set(), playhead);
    const move = (ev: PointerEvent) => {
      if (!moved && Math.abs(ev.clientX - x0) < 3) return;
      moved = true;
      let t = Math.max(0, m.t + (ev.clientX - x0) / pps);
      if (p.snapping && !ev.altKey) t = snap(t, pts, 8 / pps);
      cur = t;
      setMkDrag({ id: m.id, t });
    };
    const up = () => {
      window.removeEventListener("pointermove", move);
      setMkDrag(null);
      if (moved) { p.commit(updateMarker(timeline, m.id, { t: cur }), "Move marker"); p.seek(cur); }
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up, { once: true });
  };

  // ---- ruler scrub
  const scrub = (e: React.PointerEvent) => {
    p.seek(timeAt(e.clientX));
    const move = (ev: PointerEvent) => p.seek(timeAt(ev.clientX));
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", () => window.removeEventListener("pointermove", move), { once: true });
  };

  // ---- ruler ticks for the visible window only
  const ticks = useMemo(() => {
    const step = TICK_STEPS.find((s) => s * pps >= 90) ?? 3600;
    const minor = step / (step >= 60 ? 6 : 5);
    // integer indices avoid floating-point drift (e.g. 1.9999 labelled as "0:01")
    const perMajor = Math.round(step / minor);
    const i0 = Math.floor(view.left / pps / step) * perMajor, i1 = Math.ceil(((view.left + view.width) / pps + step) / minor);
    const out: { t: number; major: boolean }[] = [];
    for (let i = i0; i <= i1; i++) out.push({ t: Math.round(i * minor * 1e6) / 1e6, major: i % perMajor === 0 });
    return { out, step };
  }, [pps, view.left, view.width]);

  const visible = (c: Clip) => clipEnd(c) * pps >= view.left - 200 && c.start * pps <= view.left + view.width + 200;
  const invalid = drag?.preview?.error;
  const dragged = useMemo(() => (!drag?.moved ? null
    : drag.group ? expandLinked(timeline, drag.group) : new Set(linkedGroup(timeline, drag.id).map((r) => r.clip.id))),
  [drag?.moved, drag?.id, drag?.group, timeline]);
  const hasOverlays = (timeline.titles?.length ?? 0) + (timeline.blurs?.length ?? 0) > 0;
  const fullH = RULER_H + (hasOverlays ? OV_H + 1 : 0) + timeline.tracks.reduce((s, t) => s + ROW_H[t.kind] + 1, 0);
  const selected = new Set(p.selection);

  return (
    <div className="timeline">
      <div className="tl-tools">
        {p.toolbar}
        {drag && invalid && <span className="chip err">{invalid}</span>}
      </div>
      <div className="tl-body">
        <div className="tl-heads">
          <div className="ruler-spacer" />
          {hasOverlays && <div className="tl-head ov-head" style={{ height: OV_H }} title="Titles and blurs (Text and Blur tabs)"><span className="name" style={{ color: "#c77dff" }}>Text·Blur</span></div>}
          {timeline.tracks.map((t) => (
            <div key={t.id} className="tl-head" style={{ height: ROW_H[t.kind] }}>
              <span className="name" style={{ color: t.kind === "video" ? "var(--video-2)" : "var(--audio-2)" }}>{t.name}</span>
              {t.kind === "video" ? (
                <button className={"tbtn" + (t.hidden ? " on" : "")} title={t.hidden ? "Show track" : "Hide track"} onClick={() => p.onTrackToggle(t.id, "hidden")}><Icon name={t.hidden ? "eyeoff" : "eye"} size={14} /></button>
              ) : (
                <button className={"tbtn" + (t.muted ? " on" : "")} title={t.muted ? "Unmute track" : "Mute track"} onClick={() => p.onTrackToggle(t.id, "muted")}><Icon name={t.muted ? "mute" : "vol"} size={14} /></button>
              )}
              {t.kind === "audio" && p.onTrackRole && (
                <button className="tbtn" data-role={t.role ?? "dialogue"}
                  title={t.role === "music" ? "Music track (quieter while someone talks) — click to make it narration"
                    : t.role === "narration" ? "Narration track (everything else gets quieter while you talk) — click to make it dialogue"
                    : "Dialogue track — click to make it a music track"}
                  style={{ color: t.role === "music" ? "var(--accent-2)" : t.role === "narration" ? "#ffb703" : undefined }}
                  onClick={() => p.onTrackRole!(t.id, t.role === "music" ? "narration" : t.role === "narration" ? "dialogue" : "music")}>
                  <Icon name={t.role === "music" ? "music" : "mic"} size={14} />{t.role === "narration" && <span style={{ fontSize: 9, fontWeight: 700 }}>N</span>}</button>
              )}
              <button className={"tbtn" + (t.locked ? " on" : "")} title={t.locked ? "Unlock track" : "Lock track"} onClick={() => p.onTrackToggle(t.id, "locked")}><Icon name={t.locked ? "lock" : "unlock"} size={14} /></button>
              <span className="spacer" />
              {t.clips.length === 0 && timeline.tracks.filter((x) => x.kind === t.kind).length > 1 && (
                <button className="tbtn" title="Remove empty track" onClick={() => p.onRemoveTrack(t.id)}><Icon name="x" size={13} /></button>
              )}
            </div>
          ))}
        </div>

        <div className="tl-scroll" ref={scrollRef}>
          <div className="tl-canvas" style={{ width: contentW }}>
            <div className="ruler" onPointerDown={scrub} style={{ position: "relative" }}>
              {(p.slow ?? []).map((s, i) => (
                <div key={"slow" + i} data-testid="slow-stretch" title={`Nothing changes on screen for ${(s.end - s.start).toFixed(1)} s`}
                  style={{ position: "absolute", left: s.start * pps, width: Math.max(2, (s.end - s.start) * pps), top: 0, height: 4,
                    background: "rgba(255,59,48,.85)", borderRadius: 2, pointerEvents: "auto" }} />
              ))}
              {(p.markers ?? []).filter((m) => m.t * pps >= view.left - 10 && m.t * pps <= view.left + view.width + 10).map((m, i) => (
                <div key={"m" + i} title={m.title} style={{ position: "absolute", left: m.t * pps - 4, bottom: 0, width: 8, height: 8,
                  borderRadius: 2, background: m.color, transform: "rotate(45deg)", zIndex: 1, pointerEvents: "auto" }} />
              ))}
              {(p.userMarkers ?? []).map((m) => ({ ...m, t: mkDrag?.id === m.id ? mkDrag.t : m.t }))
                .filter((m) => m.t * pps >= view.left - 160 && m.t * pps <= view.left + view.width + 10).map((m) => (
                <div key={m.id} className={"umarker" + (p.markerSel === m.id ? " sel" : "")} data-testid="user-marker"
                  title={`${m.label || "Marker"} · ${fmtTime(m.t)} — click to select, drag to move`}
                  style={{ left: m.t * pps, ["--mc" as any]: m.color }} onPointerDown={(e) => startMarker(e, m)}>
                  <span>{m.label}</span>
                </div>
              ))}
              {ticks.out.map(({ t, major }) => (
                <div key={t.toFixed(4)} className={"tick" + (major ? "" : " minor")} style={{ left: t * pps }}>
                  {major && <span>{fmtTime(t, ticks.step < 1)}</span>}
                </div>
              ))}
            </div>
            {hasOverlays && (
              <div className="lane ov-lane" style={{ height: OV_H }} data-testid="overlay-lane"
                onPointerDown={(e) => { if (e.button === 0 && e.target === e.currentTarget) p.seek(timeAt(e.clientX)); }}>
                {[...(timeline.titles ?? []).map((x) => ({ kind: "title" as const, x, label: x.text || TITLE_TEMPLATES.find((tt) => tt[0] === x.template)?.[1] || "Title" })),
                  ...(timeline.blurs ?? []).map((x) => ({ kind: "blur" as const, x, label: { blur: "Blur", pixelate: "Pixelate", black: "Black box" }[x.mode] + (x.keys.length > 1 ? " · follows" : "") }))]
                  .map(({ kind, x, label }) => {
                    const cur = ov && ov.id === x.id && ovNow ? ovNow : { start: x.start, duration: x.duration };
                    const w = Math.max(6, cur.duration * pps);
                    const down = (e: React.PointerEvent, mode: OvDrag["mode"]) => {
                      if (e.button !== 0) return;
                      e.stopPropagation();
                      (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
                      setOv({ kind, id: x.id, mode, x0: e.clientX, start: x.start, duration: x.duration, moved: false });
                      setOvNow({ start: x.start, duration: x.duration });
                    };
                    return (
                      <div key={x.id} className={`ov-item ${kind}${p.overlaySel === x.id ? " sel" : ""}`} data-testid={`ov-${kind}`}
                        style={{ left: cur.start * pps, width: w }} title={`${label} · ${fmtTime(cur.start)} · ${cur.duration.toFixed(1)} s`}
                        onPointerDown={(e) => down(e, "move")}
                        onPointerMove={(e) => {
                          if (!ov || ov.id !== x.id) return;
                          const dt = (e.clientX - ov.x0) / pps;
                          if (Math.abs(e.clientX - ov.x0) > 2) ov.moved = true;
                          let start = ov.start, duration = ov.duration;
                          if (ov.mode === "move") start = Math.max(0, ov.start + dt);
                          else if (ov.mode === "end") duration = Math.max(kind === "title" ? 0.5 : 0.1, ov.duration + dt);
                          else { const s2 = Math.min(ov.start + ov.duration - 0.5, Math.max(0, ov.start + dt)); duration = ov.duration - (s2 - ov.start); start = s2; }
                          if (p.snapping && ov.mode !== "end") start = snap(start, snapPoints(timeline, new Set(), playhead), 8 / pps);
                          setOvNow({ start, duration });
                        }}
                        onPointerUp={() => {
                          const d = ov, now = ovNow;
                          setOv(null); setOvNow(null);
                          if (!d || !now) return;
                          if (!d.moved) { p.onOverlaySelect?.(kind, x.id); return; }
                          const patch = { start: now.start, duration: now.duration };
                          p.commit(kind === "title" ? updateTitle(timeline, x.id, patch) : updateBlur(timeline, x.id, patch),
                            d.mode === "move" ? `Move ${kind}` : `Resize ${kind}`);
                          p.onOverlaySelect?.(kind, x.id);
                        }}>
                        {w > 14 && <div className="handle l" onPointerDown={(e) => down(e, "start")} />}
                        {w > 30 && <span className="ov-label">{label}</span>}
                        {w > 14 && <div className="handle r" onPointerDown={(e) => down(e, "end")} />}
                      </div>
                    );
                  })}
              </div>
            )}
            {shown.tracks.map((t) => (
              <div key={t.id} ref={(el) => { laneRefs.current[t.id] = el; }}
                className={"lane" + (t.locked ? " locked" : "") + (dropTrack === t.id ? " drop" : "")} data-track={t.name}
                style={{ height: ROW_H[t.kind], ["--grid" as any]: `${ticks.step * pps}px`, backgroundPosition: `${-(view.left % (ticks.step * pps))}px 0` }}
                onPointerDown={(e) => { if (e.button === 0 && e.target === e.currentTarget) { p.setSelection([]); p.seek(timeAt(e.clientX)); } }}
                onDragOver={(e) => {
                  if (!e.dataTransfer.types.includes("application/x-rjclip-media")) return;
                  e.preventDefault(); setDropTrack(t.id);
                }}
                onDragLeave={() => setDropTrack(null)}
                onDrop={(e) => {
                  const mid = e.dataTransfer.getData("application/x-rjclip-media");
                  setDropTrack(null);
                  if (!mid) return;
                  e.preventDefault();
                  let time = timeAt(e.clientX);
                  if (p.snapping) time = snap(time, snapPoints(timeline, new Set(), playhead), 8 / pps);
                  p.onDropMedia(mid, time, t.id);
                }}>
                {t.clips.filter(visible).map((c) => {
                  const m = media[c.media_id];
                  const w = clipDuration(c) * pps;
                  const isDragged = !!dragged?.has(c.id);
                  return (
                    <div key={c.id}
                      className={`clip ${t.kind}${selected.has(c.id) ? " sel" : ""}${isDragged ? " ghost" : ""}${isDragged && invalid ? " invalid" : ""}${(t.hidden || t.muted) ? " dim" : ""}`}
                      style={{ left: c.start * pps, width: Math.max(2, w) }}
                      title={`${m?.original_name ?? "missing"} · ${fmtTime(clipDuration(c))}`}
                      onPointerDown={(e) => startDrag(e, c, "move")}>
                      {t.kind === "video" && m?.thumbnail && w > 40 && (
                        <div className="thumbs" style={{ backgroundImage: `url(${thumbUrl(p.projectId, m.id)})` }} />
                      )}
                      {t.kind === "audio" && w > 4 && <Waveform pid={p.projectId} clip={c} width={w} ready={!!m?.waveform} />}
                      {c.transition_in && <div title={`${TRANSITIONS.find((x) => x[0] === c.transition_in!.kind)?.[1] ?? "Transition"} in`} style={{ position: "absolute", left: 0, top: 0, bottom: 0,
                        width: Math.min(w / 2, c.transition_in.duration * pps), background: "linear-gradient(90deg, rgba(0,0,0,.55), transparent)", pointerEvents: "none", zIndex: 1 }} />}
                      {!!c.fade_in && <div style={{ position: "absolute", left: 0, top: 0, width: Math.min(w / 2, c.fade_in * pps), height: "100%",
                        background: "linear-gradient(to top right, rgba(0,0,0,.45) 50%, transparent 50%)", pointerEvents: "none", zIndex: 1 }} />}
                      {!!c.fade_out && <div style={{ position: "absolute", right: 0, top: 0, width: Math.min(w / 2, c.fade_out * pps), height: "100%",
                        background: "linear-gradient(to top left, rgba(0,0,0,.45) 50%, transparent 50%)", pointerEvents: "none", zIndex: 1 }} />}
                      {w > 20 && keyframeTimes(c).map((kt) => (
                        <div key={kt} className="kf-mark" style={{ left: (kt - c.start) * pps }} title={`Keyframe at ${fmtTime(kt)}`} />
                      ))}
                      {w > 30 && <div className="label">{c.label || m?.original_name || "missing media"}
                        {c.speed !== 1 && <span className="speed">{c.speed}×</span>}</div>}
                      {!t.locked && w > 14 && <>
                        <div className="handle l" onPointerDown={(e) => startDrag(e, c, "trim-start")} />
                        <div className="handle r" onPointerDown={(e) => startDrag(e, c, "trim-end")} />
                      </>}
                    </div>
                  );
                })}
              </div>
            ))}
            <div className="playhead" style={{ left: playhead * pps, height: fullH }} />
            {drag?.snapAt != null && <div className="snapline" style={{ left: drag.snapAt * pps }} />}
            {(p.userMarkers ?? []).filter((m) => p.markerSel === m.id || mkDrag?.id === m.id).map((m) => (
              <div key={"ml" + m.id} className="umarker-line" style={{ left: (mkDrag?.id === m.id ? mkDrag.t : m.t) * pps, borderColor: m.color, height: fullH }} />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
