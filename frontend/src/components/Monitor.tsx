import React, { useEffect, useRef, useState } from "react";
import { fmtTime, mediaUrl } from "../api";
import { clipAt, sourceTimeAt, timelineDuration } from "../timeline/ops";
import { activeEffects } from "../timeline/effects";
import { colorCss, cropCss, propAt } from "../timeline/keyframes";
import type { Clip, Effect, MediaMap, OutputSettings, Timeline } from "../timeline/types";
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
 * Preview limitations (export is exact): colour is a CSS approximation and transitions show as cuts.
 */
export default function Monitor({ projectId, timeline, media, output, playhead, setPlayhead, playing, setPlaying, effects = [],
  lightPreview = false, onLightPreview }: {
  projectId: string; timeline: Timeline; media: MediaMap; output: OutputSettings; effects?: Effect[];
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
  useEffect(() => {
    const el = screenRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setScr({ w: el.clientWidth, h: el.clientHeight }));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const sounds = useRef<Map<string, HTMLAudioElement>>(new Map());
  const active = activeEffects(timeline, effects, playhead);
  const zoom = active.filter(({ e }) => e.kind === "zoom").reduce((z, { e }) => Math.max(z, e.scale), 1);
  const zoomFx = active.find(({ e }) => e.kind === "zoom")?.e;
  const shaking = active.some(({ e }) => e.kind === "shake");
  const flash = active.some(({ e }) => e.kind === "flash");
  playheadRef.current = playhead;
  const videoTracks = timeline.tracks.filter((t) => t.kind === "video");
  const layers = videoTracks.map((t) => ({ track: t, clip: t.hidden ? null : clipAt(t, playhead) }));
  const hasPicture = layers.some((l) => l.clip);

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
    for (const { track, clip } of layers) {
      const v = videoRefs.current[track.id];
      if (!v) continue;
      if (clip) syncEl(v, clip.media_id, sourceTimeAt(clip, playhead), clip.speed, null);
      else syncEl(v, null, 0, 1, null);
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
      if ((e.kind === "censor" || e.kind === "sfx") && e.sound && e.sound !== "mute" && !played.current.has(e.id)) {
        const a = new Audio(`/api/sounds/${e.sound}.wav`);
        setVolume(a, e.volume);
        a.play().catch(() => {});
        sounds.current.set(e.id, a);
      }
    }
    for (const [id, a] of sounds.current) if (!ids.has(id) || !playing) { if (!a.paused && a.currentTime > 0.05 && !ids.has(id)) a.pause(); sounds.current.delete(id); }
    played.current = ids;
  }, [playhead, playing, timeline, lightPreview]);

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
      clipPath: cropCss(c.crop), filter: colorCss(c.color) || undefined,
    };
  };

  return (
    <div className="monitor">
      <div className="screen-wrap">
        <div className="screen" ref={screenRef} style={{ aspectRatio: `${ar}`, height: ar < 1 ? "100%" : undefined, width: ar >= 1 ? "100%" : undefined }}>
          <div className="stage" style={{ position: "absolute", inset: 0,
            transform: `scale(${zoom}) translate(${shaking ? Math.sin(playhead * 61) * 1.2 : 0}%, ${shaking ? Math.cos(playhead * 47) * 1.2 : 0}%)`,
            transformOrigin: zoomFx ? `${zoomFx.x * 100}% ${zoomFx.y * 100}%` : "50% 50%" }}>
            {layers.map(({ track, clip }) => (
              <video key={track.id} ref={(el) => { videoRefs.current[track.id] = el; }} muted playsInline preload="auto" data-layer={track.name}
                style={{ visibility: clip ? "visible" : "hidden", ...(clip ? layerStyle(clip) : {}) }}
                onError={() => setVideoError("This file can't play in the browser yet — a preview copy is being prepared. Export still uses the original.")}
                onLoadedData={() => setVideoError(null)} />
            ))}
          </div>
          {flash && <div style={{ position: "absolute", inset: 0, background: "rgba(255,255,255,0.8)" }} />}
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
