import React, { memo, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { fmtTime, thumbUrl, waveformUrl } from "../api";
import {
  clipDuration, clipEnd, findClip, linkedGroup, moveClip, snap, snapPoints, timelineDuration, trimEdge, type OpResult,
} from "../timeline/ops";
import type { Clip, MediaMap, Timeline, Track } from "../timeline/types";
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
      const w = Math.max(1, Math.min(4000, Math.round(width)));
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
        for (let i = i0; i < i1 && i < wf.peaks.length; i++) p = Math.max(p, wf.peaks[i]);
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
  onRemoveTrack: (trackId: string) => void;
  toolbar: React.ReactNode;
  markers?: { t: number; color: string; title: string }[];
}

export default function TimelineView(p: TimelineProps) {
  const { timeline, media, pps, playhead } = p;
  const scrollRef = useRef<HTMLDivElement>(null);
  const laneRefs = useRef<Record<string, HTMLDivElement | null>>({});
  const [drag, setDrag] = useState<Drag | null>(null);
  const dragRef = useRef<Drag | null>(null);
  const [view, setView] = useState({ left: 0, width: 1000 });
  const [dropTrack, setDropTrack] = useState<string | null>(null);
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
      const exclude = new Set(linkedGroup(timeline, d.id).map((r) => r.clip.id));
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
        preview = moveClip(timeline, d.id, s, trackAt(e.clientY, ref.track.kind) ?? ref.track.id);
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
        p.commit(d.preview, d.mode === "move" ? "Move clip" : "Trim clip");
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
    if (!p.selection.includes(clip.id) || p.selection.length > 1) p.setSelection([clip.id]);
    const track = findClip(timeline, clip.id)!.track;
    if (track.locked) return;
    const d: Drag = { mode, id: clip.id, x0: e.clientX, orig: clip, moved: false };
    dragRef.current = d;
    setDrag(d);
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
          {timeline.tracks.map((t) => (
            <div key={t.id} className="tl-head" style={{ height: ROW_H[t.kind] }}>
              <span className="name" style={{ color: t.kind === "video" ? "var(--video-2)" : "var(--audio-2)" }}>{t.name}</span>
              {t.kind === "video" ? (
                <button className={"tbtn" + (t.hidden ? " on" : "")} title={t.hidden ? "Show track" : "Hide track"} onClick={() => p.onTrackToggle(t.id, "hidden")}><Icon name={t.hidden ? "eyeoff" : "eye"} size={14} /></button>
              ) : (
                <button className={"tbtn" + (t.muted ? " on" : "")} title={t.muted ? "Unmute track" : "Mute track"} onClick={() => p.onTrackToggle(t.id, "muted")}><Icon name={t.muted ? "mute" : "vol"} size={14} /></button>
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
              {(p.markers ?? []).filter((m) => m.t * pps >= view.left - 10 && m.t * pps <= view.left + view.width + 10).map((m, i) => (
                <div key={"m" + i} title={m.title} style={{ position: "absolute", left: m.t * pps - 4, bottom: 0, width: 8, height: 8,
                  borderRadius: 2, background: m.color, transform: "rotate(45deg)", zIndex: 1, pointerEvents: "auto" }} />
              ))}
              {ticks.out.map(({ t, major }) => (
                <div key={t.toFixed(4)} className={"tick" + (major ? "" : " minor")} style={{ left: t * pps }}>
                  {major && <span>{fmtTime(t, ticks.step < 1)}</span>}
                </div>
              ))}
            </div>
            {shown.tracks.map((t) => (
              <div key={t.id} ref={(el) => { laneRefs.current[t.id] = el; }}
                className={"lane" + (t.locked ? " locked" : "") + (dropTrack === t.id ? " drop" : "")}
                style={{ height: ROW_H[t.kind], ["--grid" as any]: `${ticks.step * pps}px`, backgroundPosition: `${-(view.left % (ticks.step * pps))}px 0` }}
                onPointerDown={(e) => { if (e.button === 0 && e.target === e.currentTarget) { p.setSelection([]); p.seek(timeAt(e.clientX)); } }}
                onDragOver={(e) => {
                  if (!e.dataTransfer.types.includes("application/x-clipforge-media")) return;
                  e.preventDefault(); setDropTrack(t.id);
                }}
                onDragLeave={() => setDropTrack(null)}
                onDrop={(e) => {
                  const mid = e.dataTransfer.getData("application/x-clipforge-media");
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
                  const isDragged = drag?.moved && linkedGroup(timeline, drag.id).some((r) => r.clip.id === c.id);
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
            <div className="playhead" style={{ left: playhead * pps, height: RULER_H + timeline.tracks.reduce((s, t) => s + ROW_H[t.kind] + 1, 0) }} />
            {drag?.snapAt != null && <div className="snapline" style={{ left: drag.snapAt * pps }} />}
          </div>
        </div>
      </div>
    </div>
  );
}
