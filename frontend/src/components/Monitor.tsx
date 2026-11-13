import React, { useEffect, useRef, useState } from "react";
import { effectSoundUrl, fmtTime, mediaUrl } from "../api";
import { blurAt, clipAt, clipEnd, sourceTimeAt, timelineDuration, transitionAt } from "../timeline/ops";
import { transitionLook } from "../timeline/transitionCss";
import { activeEffects } from "../timeline/effects";
import { colorCss, cropCss, lookOverlay, propAt } from "../timeline/keyframes";
import { camAspect, camAt, layoutBox } from "../timeline/facecam";
import TitlesPreview from "./TitlesPreview";
import OverlaysPreview from "./OverlaysPreview";
import { tallyInfo } from "../timeline/phase18";
import CaptionsPreview from "./CaptionsPreview";
import type { CapChunk } from "../timeline/captions";
import type { CaptionSettings, Clip, Effect, FaceCam, MediaMap, OutputSettings, Timeline } from "../timeline/types";
import { Icon } from "./ui";

/**
 * Program monitor: plays the *timeline* (not a single file).
 *
 * A master clock (performance.now) drives the playhead. Every visible video track gets its
 * own muted <video> layer (V1 at the bottom), drawn with the clip's scale, position,
 * rotation, opacity and crop — including keyframes — so picture-in-picture looks like the
 * export. Each audio track gets an <audio> element routed through Web Audio (per-track gain,
 * so volume above 100% previews too) into a stereo peak meter. Elements are re-seeked only
 * when they drift > 0.25 s, so playback stays smooth.
 *
 * Preview limitations (export is exact): colour and transitions are CSS look-alikes.
 */
export default function Monitor({ projectId, timeline, media, output, playhead, setPlayhead, playing, setPlaying, effects = [],
  lightPreview = false, onLightPreview, facecam = null, drawBox, drawMessage, pickPoints = null, captions = null, titleSel = null, onTitleMove, watermark = null }: {
  /** burned-in captions to preview (only when they're switched on) */
  captions?: { chunks: CapChunk[]; settings: CaptionSettings } | null;
  /** the selected title (pop-up words and shapes can be dragged on the picture) */
  titleSel?: string | null; onTitleMove?: (id: string, x: number, y: number, done: boolean) => void;
  /** brand kit logo (Phase 15) */
  watermark?: { file: string; corner: "tl" | "tr" | "bl" | "br"; size: number; opacity: number } | null;
  projectId: string; timeline: Timeline; media: MediaMap; output: OutputSettings; effects?: Effect[]; facecam?: FaceCam | null;
  /** when set, dragging on the picture draws a box (frame fractions) and calls this */
  drawBox?: ((box: { x: number; y: number; w: number; h: number }) => void) | null;
  /** what to say while drawing a box (default: the privacy blur's message) */
  drawMessage?: string;
  /** Phase 19: click points on the picture (a route); Enter or Done finishes */
  pickPoints?: { points: [number, number][]; onPoint: (x: number, y: number) => void; onDone: () => void } | null;
  playhead: number; setPlayhead: (t: number) => void; playing: boolean; setPlaying: (p: boolean) => void;
  lightPreview?: boolean; onLightPreview?: (on: boolean) => void;
}) {
  const videoRefs = useRef<Record<string, HTMLVideoElement | null>>({});
  const audioRefs = useRef<Record<string, HTMLAudioElement | null>>({});
  const clock = useRef<{ t0: number; p0: number } | null>(null);
  const [videoError, setVideoError] = useState<string | null>(null);
  const duration = timelineDuration(timeline);
  const playheadRef = useRef(playhead);
  const played = useRef<Set<string>>(new Set());
  const screenRef = useRef<HTMLDivElement>(null);
  const [scr, setScr] = useState({ w: 640, h: 360 });
  // the space the picture may use (the wrap minus its padding); the screen gets the largest
  // size with the video's shape that fits — never cropped when the preview area is short
  const wrapRef = useRef<HTMLDivElement>(null);
  const [room, setRoom] = useState<{ w: number; h: number } | null>(null);
  useEffect(() => {
    const el = screenRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setScr({ w: el.clientWidth, h: el.clientHeight }));
    ro.observe(el);
    const wrap = wrapRef.current;
    const rw = wrap ? new ResizeObserver(() => {
      const cs = getComputedStyle(wrap);
      const w = wrap.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
      const h = wrap.clientHeight - parseFloat(cs.paddingTop) - parseFloat(cs.paddingBottom);
      setRoom(w > 0 && h > 0 ? { w, h } : null);
    }) : null;
    if (wrap && rw) rw.observe(wrap);
    return () => { ro.disconnect(); rw?.disconnect(); };
  }, []);
  const sounds = useRef<Map<string, HTMLAudioElement>>(new Map());
  const active = activeEffects(timeline, effects, playhead);
  const zoom = active.filter(({ e }) => e.kind === "zoom").reduce((z, { e }) => Math.max(z, e.scale), 1);
  const zoomFx = active.find(({ e }) => e.kind === "zoom")?.e;
  const shaking = active.some(({ e }) => e.kind === "shake");
  const flash = active.some(({ e }) => e.kind === "flash");
  playheadRef.current = playhead;
  const videoTracks = timeline.tracks.filter((t) => t.kind === "video");
  const layers = videoTracks.map((t) => {
    const tr = t.hidden ? null : transitionAt(t, playhead);
    return { track: t, clip: tr ? tr.b : t.hidden ? null : clipAt(t, playhead), tr };
  });
  const outRefs = useRef<Record<string, HTMLVideoElement | null>>({});
  const hasPicture = layers.some((l) => l.clip);
  const camAsset = facecam ? media[facecam.media_id] : undefined;
  const cam = camAt(timeline, facecam, camAsset, playhead);
  const camRef = useRef<HTMLVideoElement | null>(null);
  const [drag, setDrag] = useState<{ x0: number; y0: number; x1: number; y1: number } | null>(null);
  const [guides, setGuides] = useState(() => { try { return localStorage.getItem("cf:guides") === "1"; } catch { return false; } });

  // ---- Web Audio: per-element gain -> master -> stereo analysers (meters)
  const audio = useRef<{ ctx: AudioContext; master: GainNode; an: [AnalyserNode, AnalyserNode]; gains: Map<HTMLMediaElement, GainNode> } | null>(null);
  const ensureAudio = () => {
    if (audio.current) { if (audio.current.ctx.state === "suspended") audio.current.ctx.resume().catch(() => {}); return audio.current; }
    const AC = window.AudioContext || (window as any).webkitAudioContext;
    if (!AC) return null;
    try {
      const ctx: AudioContext = new AC();
      const master = ctx.createGain();
      master.channelCount = 2; master.channelCountMode = "explicit"; master.channelInterpretation = "speakers";
      const split = ctx.createChannelSplitter(2);
      const an: [AnalyserNode, AnalyserNode] = [ctx.createAnalyser(), ctx.createAnalyser()];
      an.forEach((a, i) => { a.fftSize = 1024; split.connect(a, i); });
      master.connect(ctx.destination); master.connect(split);
      audio.current = { ctx, master, an, gains: new Map() };
      return audio.current;
    } catch { return null; }
  };
  const setVolume = (el: HTMLMediaElement, vol: number) => {
    const a = audio.current;
    if (!a) { el.volume = Math.max(0, Math.min(1, vol)); return; }
    let g = a.gains.get(el);
    if (!g) {
      try {
        const src = a.ctx.createMediaElementSource(el);
        g = a.ctx.createGain();
        src.connect(g); g.connect(a.master);
        a.gains.set(el, g);
        el.volume = 1;
      } catch { el.volume = Math.max(0, Math.min(1, vol)); return; }
    }
    g.gain.value = Math.max(0, vol);
  };
  useEffect(() => () => { audio.current?.ctx.close().catch(() => {}); }, []);

  // ---- meters (drawn straight to the DOM; no React re-render per frame)
  const meterRefs = useRef<(HTMLDivElement | null)[]>([]);
  const clipRefs = useRef<(HTMLDivElement | null)[]>([]);
  useEffect(() => {
    let raf = 0;
    const lvl = [-60, -60], hold = [{ v: -60, at: 0 }, { v: -60, at: 0 }];
    const buf = new Float32Array(1024);
    const tick = () => {
      const a = audio.current;
      for (let i = 0; i < 2; i++) {
        let peak = 0;
        if (a) {
          a.an[i].getFloatTimeDomainData(buf);
          for (let k = 0; k < buf.length; k++) peak = Math.max(peak, Math.abs(buf[k]));
        }
        const db = peak > 0 ? Math.max(-60, 20 * Math.log10(peak)) : -60;
        lvl[i] = Math.max(db, lvl[i] - 1.2);
        const now = performance.now();
        if (db >= hold[i].v || now - hold[i].at > 1500) hold[i] = { v: db, at: now };
        const bar = meterRefs.current[i];
        if (bar) {
          bar.style.height = `${((lvl[i] + 60) / 60) * 100}%`;
          bar.style.background = lvl[i] > -3 ? "var(--err)" : lvl[i] > -12 ? "var(--warn, #f2b84b)" : "var(--ok)";
          bar.parentElement?.style.setProperty("--hold", `${((hold[i].v + 60) / 60) * 100}%`);
        }
        const c = clipRefs.current[i];
        if (c && peak >= 0.999) c.classList.add("on");
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, []);

  // ---- master clock
  useEffect(() => {
    if (!playing) { clock.current = null; return; }
    ensureAudio();
    if (playheadRef.current >= duration - 0.01) setPlayhead(0);
    clock.current = { t0: performance.now(), p0: playheadRef.current >= duration - 0.01 ? 0 : playheadRef.current };
    let raf = 0;
    const tick = () => {
      const c = clock.current;
      if (!c) return;
      const t = c.p0 + (performance.now() - c.t0) / 1000;
      if (t >= duration) { setPlayhead(duration); setPlaying(false); return; }
      setPlayhead(t);
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [playing, duration]);

  // if the user scrubs while playing, restart the clock from the new spot
  useEffect(() => {
    if (playing && clock.current) {
      const expected = clock.current.p0 + (performance.now() - clock.current.t0) / 1000;
      if (Math.abs(expected - playhead) > 0.3) clock.current = { t0: performance.now(), p0: playhead };
    }
  }, [playhead, playing]);

  const urlOf = (mid: string) => {
    const m = media[mid];
    return mediaUrl(projectId, mid) + (lightPreview && m?.proxy ? "?proxy=1" : "");
  };

  // ---- sync a media element to a clip
  const syncEl = (el: HTMLMediaElement, mediaId: string | null, srcTime: number, rate: number, vol: number | null) => {
    if (!mediaId) {
      if (!el.paused) el.pause();
      return;
    }
    const url = urlOf(mediaId);
    if (el.dataset.url !== url) {
      el.dataset.url = url;
      el.src = url;
      el.currentTime = srcTime;
    }
    el.playbackRate = rate;
    if (vol !== null) setVolume(el, vol);
    if (el.readyState >= 1) {
      const drift = Math.abs(el.currentTime - srcTime);
      if (!playing ? drift > 0.02 : drift > 0.25) el.currentTime = srcTime;
    }
    if (playing && el.paused) el.play().catch(() => {});
    if (!playing && !el.paused) el.pause();
  };

  useEffect(() => {
    for (const { track, clip, tr } of layers) {
      const v = videoRefs.current[track.id];
      if (!v) continue;
      if (tr) syncEl(v, tr.b.media_id, tr.bTime, tr.b.speed, null);
      else if (clip) syncEl(v, clip.media_id, sourceTimeAt(clip, playhead), clip.speed, null);
      else syncEl(v, null, 0, 1, null);
      const o = outRefs.current[track.id];       // the outgoing clip during a transition
      if (o) {
        if (tr) syncEl(o, tr.a.media_id, Math.min(tr.aTime, (media[tr.a.media_id]?.duration ?? tr.aTime) - 0.04), tr.a.speed, null);
        else syncEl(o, null, 0, 1, null);
      }
    }
    if (camRef.current) {
      if (cam && facecam) syncEl(camRef.current, facecam.media_id, cam.camTime, cam.speed, null);
      else syncEl(camRef.current, null, 0, 1, null);
    }
    const censoring = active.some(({ e }) => e.kind === "censor");
    for (const track of timeline.tracks) {
      if (track.kind !== "audio") continue;
      const el = audioRefs.current[track.id];
      if (!el) continue;
      const c = track.muted ? null : clipAt(track, playhead);
      if (c) syncEl(el, c.media_id, sourceTimeAt(c, playhead), c.speed, censoring ? 0 : propAt(c, "volume", playhead));
      else syncEl(el, null, 0, 1, null);
    }
    // trigger bleep / sound-effect previews once when their window starts
    const ids = new Set(active.map(({ e }) => e.id));
    if (playing) for (const { e } of active) {
      const url = (e.kind === "censor" || e.kind === "sfx") ? effectSoundUrl(projectId, e.sound, e.sound_asset) : null;
      if (url && !played.current.has(e.id)) {
        const a = new Audio(url);
        setVolume(a, e.volume);
        a.play().catch(() => {});
        sounds.current.set(e.id, a);
      }
    }
    for (const [id, a] of sounds.current) if (!ids.has(id) || !playing) { if (!a.paused && a.currentTime > 0.05 && !ids.has(id)) a.pause(); sounds.current.delete(id); }
    played.current = ids;
  }, [playhead, playing, timeline, lightPreview, facecam]);

  /** Face cam: same box, crop, shape and border as the export (background removal is export-only). */
  const camLayer = () => {
    if (!facecam || !camAsset) return null;
    const full = !!cam?.full;
    const box = full ? { x: 0, y: 0, w: 1, h: 1 } : layoutBox(facecam, output.width, output.height, camAspect(facecam, camAsset));
    const k = scr.w / output.width;                       // same scale both ways, like the other layers
    const oy = (scr.h - output.height * k) / 2;
    const bw = box.w * output.width * k, bh = box.h * output.height * k;
    const crop = full ? { left: 0, right: 0, top: 0, bottom: 0 } : facecam.crop;
    const vw = camAsset.width || 16, vh = camAsset.height || 9;
    const cw = vw * (1 - crop.left - crop.right), ch = vh * (1 - crop.top - crop.bottom);
    const s = Math.max(bw / cw, bh / ch);
    const shape = full ? "rect" : facecam.shape;
    const border = full || facecam.remove_bg ? 0 : facecam.border * output.width * k;
    const shadows = [border ? `0 0 0 ${border}px ${facecam.border_color}` : "", !full && facecam.shadow && !facecam.remove_bg ? `0 ${scr.w * 0.004}px ${scr.w * 0.012}px rgba(0,0,0,.55)` : ""].filter(Boolean);
    return (
      <div data-testid="facecam-layer" title="Face cam" style={{ position: "absolute", zIndex: 1000, left: box.x * output.width * k, top: oy + box.y * output.height * k, width: bw, height: bh,
        overflow: "hidden", borderRadius: shape === "circle" ? "50%" : shape === "rounded" ? Math.min(bw, bh) * 0.12 : 0,
        boxShadow: shadows.join(", ") || undefined, opacity: cam ? cam.alpha : 0, visibility: cam ? "visible" : "hidden" }}>
        <video ref={camRef} muted playsInline preload="auto" style={{ position: "absolute", maxWidth: "none", objectFit: "fill",
          width: vw * s, height: vh * s, left: -crop.left * vw * s - (cw * s - bw) / 2, top: -crop.top * vh * s - (ch * s - bh) / 2 }} />
      </div>
    );
  };

  const step = (frames: number) => { setPlaying(false); setPlayhead(Math.max(0, Math.min(duration, playhead + frames / output.fps))); };
  const ar = output.width / output.height;

  /** Same geometry as the renderer: fit (or fill) the canvas, then scale/rotate about the centre and move. */
  const layerStyle = (c: Clip): React.CSSProperties => {
    const m = media[c.media_id];
    const k = scr.w / output.width;
    const mw = m?.width || output.width, mh = m?.height || output.height;
    const fit = output.fit_mode === "fill" ? Math.max(output.width / mw, output.height / mh) : Math.min(output.width / mw, output.height / mh);
    const w = mw * fit * k, h = mh * fit * k;
    const s = propAt(c, "scale", playhead), x = propAt(c, "x", playhead) * k, y = propAt(c, "y", playhead) * k;
    const r = propAt(c, "rotation", playhead), o = propAt(c, "opacity", playhead);
    return {
      left: (scr.w - w) / 2, top: (scr.h - h) / 2, right: "auto", bottom: "auto", width: w, height: h, objectFit: "fill",
      transform: `translate(${x}px, ${y}px) rotate(${r}deg) scale(${s})`, opacity: o,
      clipPath: cropCss(c.crop), filter: [colorCss(c.color), c.chroma ? `url(#ck-${c.id})` : ""].filter(Boolean).join(" ") || undefined,
      ...(c.chroma ? { background: "transparent" } : {}),
    };
  };
  // green screen look-alike: an SVG colour matrix that turns pixels near the key colour see-through
  const keyed = timeline.tracks.flatMap((t) => t.clips).filter((c) => c.chroma && c.start <= playhead + 1 && clipEnd(c) >= playhead - 1);

  return (
    <div className="monitor">
      {keyed.length > 0 && (
        <svg width="0" height="0" style={{ position: "absolute" }} aria-hidden="true">
          <defs>{keyed.map((c) => <filter key={c.id} id={`ck-${c.id}`} colorInterpolationFilters="sRGB" x="0" y="0" width="1" height="1"><feColorMatrix type="matrix" values={chromaMatrix(c.chroma!)} /></filter>)}</defs>
        </svg>
      )}
      <div className="screen-wrap" ref={wrapRef}>
        <div className="screen" ref={screenRef} style={room
          ? { width: Math.floor(Math.min(room.w, room.h * ar)), height: Math.floor(Math.min(room.w, room.h * ar) / ar) }
          : { aspectRatio: `${ar}`, height: ar < 1 ? "100%" : undefined, width: ar >= 1 ? "100%" : undefined }}>
          <div className="stage" style={{ position: "absolute", inset: 0,
            transform: `scale(${zoom}) translate(${shaking ? Math.sin(playhead * 61) * 1.2 : 0}%, ${shaking ? Math.cos(playhead * 47) * 1.2 : 0}%)`,
            transformOrigin: zoomFx ? `${zoomFx.x * 100}% ${zoomFx.y * 100}%` : "50% 50%" }}>
            {layers.map(({ track, clip, tr }, li) => {
              const z = li * 4;  // keep upper tracks above lower ones
              const look = tr ? transitionLook(tr.kind, tr.p) : null;
              const merge = (base: React.CSSProperties, extra: React.CSSProperties | undefined): React.CSSProperties => !extra ? base : {
                ...base, ...extra,
                opacity: ((base.opacity as number) ?? 1) * ((extra.opacity as number) ?? 1),
                filter: [base.filter, extra.filter].filter(Boolean).join(" ") || undefined,
              };
              return (
                <React.Fragment key={track.id}>
                  <video ref={(el) => { outRefs.current[track.id] = el; }} muted playsInline preload="auto" data-layer={track.name + "-out"} data-testid="transition-out"
                    style={{ visibility: tr ? "visible" : "hidden", zIndex: z + (look?.aOnTop ? 2 : 0), ...(tr ? merge(layerStyle(tr.a), look!.a) : {}) }} />
                  <video ref={(el) => { videoRefs.current[track.id] = el; }} muted playsInline preload="auto" data-layer={track.name}
                    style={{ visibility: clip ? "visible" : "hidden", zIndex: z + 1, ...(clip ? merge(layerStyle(clip), look?.b) : {}) }}
                    onError={() => setVideoError("This file can't play in the browser yet — a preview copy is being prepared. Export still uses the original.")}
                    onLoadedData={() => setVideoError(null)} />
                  {clip && !tr && lookOverlay(clip.color?.look) && (() => {
                    const ls = layerStyle(clip);
                    return <div data-testid="look-overlay" data-look={clip.color?.look} style={{ position: "absolute", zIndex: z + 2, pointerEvents: "none",
                      left: ls.left, top: ls.top, width: ls.width, height: ls.height, transform: ls.transform, opacity: ls.opacity, clipPath: ls.clipPath,
                      ...lookOverlay(clip.color?.look) } as React.CSSProperties} />;
                  })()}
                  {look?.overlay && <div data-testid="transition-overlay" style={{ position: "absolute", inset: 0, zIndex: z + 3, pointerEvents: "none", ...look.overlay }} />}
                </React.Fragment>
              );
            })}
            {camLayer()}
          </div>
          {flash && <div style={{ position: "absolute", inset: 0, background: "rgba(255,255,255,0.8)" }} />}
          {(timeline.blurs ?? []).filter((b) => playhead >= b.start && playhead < b.start + b.duration).map((b) => {
            const k = scr.w / output.width, oy = (scr.h - output.height * k) / 2, box = blurAt(b, playhead);
            const w = box.w * output.width * k, h = box.h * output.height * k;
            return <div key={b.id} data-testid="blur-preview" style={{ position: "absolute", left: box.x * output.width * k, top: oy + box.y * output.height * k,
              width: w, height: h, borderRadius: b.shape === "ellipse" ? "50%" : 0, pointerEvents: "none",
              background: b.mode === "black" ? "#000" : undefined,
              backdropFilter: b.mode === "black" ? undefined : `blur(${Math.max(2, b.strength * Math.min(w, h) / (b.mode === "pixelate" ? 6 : 8))}px)`,
              WebkitBackdropFilter: b.mode === "black" ? undefined : `blur(${Math.max(2, b.strength * Math.min(w, h) / 8)}px)` } as React.CSSProperties} />;
          })}
          {drawBox && (() => {
            const k = scr.w / output.width, oy = (scr.h - output.height * k) / 2;
            const rel = (e: React.PointerEvent) => { const r = (e.currentTarget as HTMLElement).getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; };
            return (
              <div data-testid="draw-layer" style={{ position: "absolute", inset: 0, cursor: "crosshair", zIndex: 5, background: "rgba(76,201,240,.06)" }}
                onPointerDown={(e) => { (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId); const [x, y] = rel(e); setDrag({ x0: x, y0: y, x1: x, y1: y }); }}
                onPointerMove={(e) => { if (drag) { const [x, y] = rel(e); setDrag({ ...drag, x1: x, y1: y }); } }}
                onPointerUp={() => {
                  if (!drag) return;
                  const fw = output.width * k, fh = output.height * k;
                  const x = Math.min(drag.x0, drag.x1) / fw, y = (Math.min(drag.y0, drag.y1) - oy) / fh;
                  const w = Math.abs(drag.x1 - drag.x0) / fw, h = Math.abs(drag.y1 - drag.y0) / fh;
                  setDrag(null);
                  if (w > 0.01 && h > 0.01) drawBox({ x, y, w, h });
                }}>
                {drag && <div style={{ position: "absolute", left: Math.min(drag.x0, drag.x1), top: Math.min(drag.y0, drag.y1),
                  width: Math.abs(drag.x1 - drag.x0), height: Math.abs(drag.y1 - drag.y0), border: "2px dashed #4cc9f0" }} />}
                {!drag && <div className="overlay-msg" style={{ pointerEvents: "none" }}>{drawMessage ?? "Drag over what you want to hide"}</div>}
              </div>
            );
          })()}
          {pickPoints && (() => {
            const k = scr.w / output.width, oy = (scr.h - output.height * k) / 2;
            const fw = output.width * k, fh = output.height * k;
            const px = pickPoints.points.map(([x, y]) => [x * fw, oy + y * fh]);
            return (
              <div data-testid="pick-layer" tabIndex={-1} style={{ position: "absolute", inset: 0, cursor: "crosshair", zIndex: 5, background: "rgba(255,59,48,.05)" }}
                onPointerDown={(e) => {
                  const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
                  const x = (e.clientX - r.left) / fw, y = (e.clientY - r.top - oy) / fh;
                  if (x >= 0 && x <= 1 && y >= 0 && y <= 1) pickPoints.onPoint(+x.toFixed(4), +y.toFixed(4));
                }}>
                <svg width={scr.w} height={scr.h} style={{ position: "absolute", inset: 0, pointerEvents: "none" }}>
                  <polyline points={px.map((p) => p.join(",")).join(" ")} fill="none" stroke="#ff3b30" strokeWidth={3} strokeDasharray="6 4" />
                  {px.map(([x, y], i) => <circle key={i} cx={x} cy={y} r={5} fill="#fff" stroke="#ff3b30" strokeWidth={2} />)}
                </svg>
                <div className="overlay-msg" style={{ pointerEvents: "none", alignItems: "start", paddingTop: 12 }}>
                  Click along the route ({pickPoints.points.length}/20 points) — press Enter or Done when finished</div>
                <button className="btn sm primary" style={{ position: "absolute", right: 10, bottom: 10 }}
                  onPointerDown={(e) => e.stopPropagation()} onClick={pickPoints.onDone}>Done</button>
              </div>
            );
          })()}
          {guides && <SafeGuides vertical={output.height > output.width} k={scr.w / output.width} W={output.width} H={output.height}
            oy={(scr.h - output.height * (scr.w / output.width)) / 2} />}
          {(timeline.titles?.length ?? 0) > 0 && <TitlesPreview titles={timeline.titles!} t={playhead} k={scr.w / output.width}
            W={output.width} H={output.height} ox={0} oy={(scr.h - output.height * (scr.w / output.width)) / 2}
            sel={titleSel} onMove={onTitleMove} tally={(x) => tallyInfo(timeline, effects, x)} />}
          {((timeline.counters?.length ?? 0) > 0 || timeline.name_tags?.enabled) && <OverlaysPreview projectId={projectId} timeline={timeline}
            effects={effects} t={playhead} k={scr.w / output.width} W={output.width} H={output.height}
            oy={(scr.h - output.height * (scr.w / output.width)) / 2} />}
          {watermark && (() => {
            const k = scr.w / output.width, oy = (scr.h - output.height * k) / 2;
            const m = { x: output.width * 0.03 * k, y: output.height * 0.03 * k };
            return <img data-testid="watermark-preview" src={`/api/projects/${projectId}/brand/watermark.png?f=${watermark.file}`} alt=""
              style={{ position: "absolute", zIndex: 1700, pointerEvents: "none", opacity: watermark.opacity, width: output.width * watermark.size * k,
                ...(watermark.corner.endsWith("l") ? { left: m.x } : { right: m.x }),
                ...(watermark.corner.startsWith("t") ? { top: oy + m.y } : { bottom: oy + m.y }) }} />;
          })()}
          {captions?.settings.enabled && captions.chunks.length > 0 && <CaptionsPreview chunks={captions.chunks} cs={captions.settings} t={playhead}
            k={scr.w / output.width} W={output.width} H={output.height} ox={0} oy={(scr.h - output.height * (scr.w / output.width)) / 2} />}
          {active.filter(({ e }) => e.kind === "text" || e.kind === "image").map(({ e }) => (
            <div key={e.id} style={{ position: "absolute", left: `${e.x * 100}%`, top: `${e.y * 100}%`, transform: "translate(-50%,-50%)", pointerEvents: "none" }}>
              {e.kind === "text" ? (
                <span style={{ fontFamily: "Impact, 'Arial Black', sans-serif", fontSize: e.size * scr.h, color: e.color, whiteSpace: "nowrap",
                  WebkitTextStroke: "2px #000", textShadow: "0 3px 6px rgba(0,0,0,.6)" }}>{e.text}</span>
              ) : <img src={`/api/projects/${projectId}/fx/images/${e.asset}`} style={{ width: e.size * 2.5 * scr.w, maxWidth: "none", display: "block" }} />}
            </div>
          ))}
          {!hasPicture && <div className="overlay-msg">{duration > 0 ? "" : "Add media to the timeline to preview it here"}</div>}
          {hasPicture && videoError && <div className="overlay-msg">{videoError}</div>}
        </div>
        <div className="meters" title="Audio level (peak, dBFS). Red = close to clipping." data-testid="meters">
          {[0, 1].map((i) => (
            <div key={i} className="meter">
              <div className="meter-clip" ref={(el) => { clipRefs.current[i] = el; }} onClick={(e) => e.currentTarget.classList.remove("on")} title="Clipped — click to reset" />
              <div className="meter-track"><div className="meter-bar" ref={(el) => { meterRefs.current[i] = el; }} /><div className="meter-hold" /></div>
              <div className="meter-lbl">{i ? "R" : "L"}</div>
            </div>
          ))}
        </div>
      </div>
      {timeline.tracks.filter((t) => t.kind === "audio").map((t) => (
        <audio key={t.id} ref={(el) => { audioRefs.current[t.id] = el; }} preload="auto" />
      ))}
      <div className="transport">
        <button className="btn icon ghost" title="Go to start (Home)" onClick={() => { setPlaying(false); setPlayhead(0); }}><Icon name="start" /></button>
        <button className="btn icon ghost" title="Previous frame (←)" onClick={() => step(-1)}><Icon name="prev" /></button>
        <button className="btn icon" title="Play / pause (Space)" onClick={() => { ensureAudio(); setPlaying(!playing); }} disabled={duration <= 0}>
          <Icon name={playing ? "pause" : "play"} />
        </button>
        <button className="btn icon ghost" title="Next frame (→)" onClick={() => step(1)}><Icon name="next" /></button>
        <button className="btn icon ghost" title="Go to end (End)" onClick={() => { setPlaying(false); setPlayhead(duration); }}><Icon name="end" /></button>
        <span className="tc">{fmtTime(playhead)}</span>
        <span className="muted mono" style={{ fontSize: 12 }}>/ {fmtTime(duration)}</span>
        <span className="spacer" />
        <button className={"btn sm" + (guides ? " on" : " ghost")} aria-label="Safe-area guides"
          title={output.height > output.width ? "Show where YouTube Shorts puts its buttons and captions" : "Show title-safe and action-safe areas"}
          onClick={() => { setGuides(!guides); try { localStorage.setItem("cf:guides", guides ? "0" : "1"); } catch { /* storage unavailable */ } }}>
          <Icon name="guides" size={14} />Guides</button>
        {onLightPreview && (
          <button className={"btn sm" + (lightPreview ? " on" : " ghost")} onClick={() => onLightPreview(!lightPreview)}
            title="Play small 540p preview copies instead of the full files — smoother on slow computers. Exports always use the originals.">
            {lightPreview ? "Light preview on" : "Light preview"}
          </button>
        )}
        <span className="muted" style={{ fontSize: 11 }}>{output.width}×{output.height} · {output.fps} fps</span>
      </div>
    </div>
  );
}

/** Safe areas: title-safe (90%) and action-safe (93%) for landscape; for vertical Shorts,
 *  roughly where YouTube's own buttons and text sit (keep important things out of them). */
function SafeGuides({ vertical, k, W, H, oy }: { vertical: boolean; k: number; W: number; H: number; oy: number }) {
  const w = W * k, h = H * k;
  const box = (f: number, style: React.CSSProperties) => (
    <div style={{ position: "absolute", left: w * (1 - f) / 2, top: oy + h * (1 - f) / 2, width: w * f, height: h * f, pointerEvents: "none", ...style }} />
  );
  const zone = (x: number, y: number, zw: number, zh: number, label: string) => (
    <div style={{ position: "absolute", left: x * w, top: oy + y * h, width: zw * w, height: zh * h, background: "rgba(255,60,60,.18)",
      border: "1px dashed rgba(255,120,120,.8)", color: "#fff", fontSize: 10, padding: 3, boxSizing: "border-box", pointerEvents: "none",
      textShadow: "0 0 3px #000" }}>{label}</div>
  );
  return (
    <div data-testid="safe-guides" style={{ position: "absolute", inset: 0, pointerEvents: "none", zIndex: 6 }}>
      {vertical ? (<>
        {zone(0, 0, 1, 0.07, "YouTube: search & menu")}
        {zone(0.86, 0.42, 0.14, 0.42, "like · comment · share")}
        {zone(0, 0.8, 0.86, 0.2, "channel, title, sound")}
      </>) : (<>
        {box(0.93, { border: "1px dashed rgba(255,255,255,.55)" })}
        {box(0.9, { border: "1px dotted rgba(255,222,0,.7)" })}
        <div style={{ position: "absolute", left: w / 2 - 8, top: oy + h / 2, width: 16, height: 1, background: "rgba(255,255,255,.6)" }} />
        <div style={{ position: "absolute", left: w / 2, top: oy + h / 2 - 8, width: 1, height: 16, background: "rgba(255,255,255,.6)" }} />
      </>)}
    </div>
  );
}

/** Alpha row of a colour matrix for a key colour: the key's strongest channel minus the
 *  other two, scaled by how strict "similarity" is. Close to green → see-through. */
export function chromaMatrix(ch: { color: string; similarity: number }): string {
  const rgb = [1, 3, 5].map((i) => parseInt(ch.color.slice(i, i + 2), 16) / 255);
  const d = rgb.indexOf(Math.max(...rgb));
  const k = 0.6 / Math.max(0.05, ch.similarity);
  const a = [0, 1, 2].map((i) => (i === d ? -2 * k : k));
  // the +1 comes from the pixel's own alpha (not a constant), so see-through stays see-through
  return `1 0 0 0 0  0 1 0 0 0  0 0 1 0 0  ${a[0]} ${a[1]} ${a[2]} 1 0`;
}

