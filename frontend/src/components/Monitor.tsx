import React, { useEffect, useRef, useState } from "react";
import { fmtTime, mediaUrl } from "../api";
import { clipAt, sourceTimeAt, timelineDuration, topVideoClipAt } from "../timeline/ops";
import { activeEffects } from "../timeline/effects";
import type { Effect, MediaMap, OutputSettings, Timeline } from "../timeline/types";
import { Icon } from "./ui";

/**
 * Program monitor: plays the *timeline* (not a single file).
 *
 * A master clock (performance.now) drives the playhead. One <video> element shows the
 * top-most visible video clip; each audio track gets its own hidden <audio> element so
 * multi-track audio is actually mixed in preview. Elements are re-seeked only when they
 * drift > 0.25 s, so playback stays smooth.
 *
 * Preview limitations (export is exact): only the top-most video layer is shown,
 * transforms aren't previewed, and volume above 100% previews as 100%.
 */
export default function Monitor({ projectId, timeline, media, output, playhead, setPlayhead, playing, setPlaying, effects = [] }: {
  projectId: string; timeline: Timeline; media: MediaMap; output: OutputSettings; effects?: Effect[];
  playhead: number; setPlayhead: (t: number) => void; playing: boolean; setPlaying: (p: boolean) => void;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const audioRefs = useRef<Record<string, HTMLAudioElement | null>>({});
  const clock = useRef<{ t0: number; p0: number } | null>(null);
  const [videoError, setVideoError] = useState<string | null>(null);
  const [hasPicture, setHasPicture] = useState(false);
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

  // ---- master clock
  useEffect(() => {
    if (!playing) { clock.current = null; return; }
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
  const lastSet = useRef(playhead);
  useEffect(() => {
    if (playing && clock.current) {
      const expected = clock.current.p0 + (performance.now() - clock.current.t0) / 1000;
      if (Math.abs(expected - playhead) > 0.3) clock.current = { t0: performance.now(), p0: playhead };
    }
    lastSet.current = playhead;
  }, [playhead, playing]);

  // ---- sync a media element to a clip
  const syncEl = (el: HTMLMediaElement, mediaId: string | null, srcTime: number, rate: number, vol: number) => {
    if (!mediaId) {
      if (!el.paused) el.pause();
      return;
    }
    const url = mediaUrl(projectId, mediaId);
    if (el.dataset.mid !== mediaId) {
      el.dataset.mid = mediaId;
      el.src = url;
      el.currentTime = srcTime;
    }
    el.playbackRate = rate;
    el.volume = Math.max(0, Math.min(1, vol));
    if (el.readyState >= 1) {
      const drift = Math.abs(el.currentTime - srcTime);
      if (!playing ? drift > 0.02 : drift > 0.25) el.currentTime = srcTime;
    }
    if (playing && el.paused) el.play().catch(() => {});
    if (!playing && !el.paused) el.pause();
  };

  useEffect(() => {
    const v = videoRef.current;
    if (v) {
      const hit = topVideoClipAt(timeline, playhead);
      setHasPicture(!!hit);
      if (hit) syncEl(v, hit.clip.media_id, sourceTimeAt(hit.clip, playhead), hit.clip.speed, 0);
      else syncEl(v, null, 0, 1, 0);
    }
    const censoring = active.some(({ e }) => e.kind === "censor");
    for (const track of timeline.tracks) {
      if (track.kind !== "audio") continue;
      const el = audioRefs.current[track.id];
      if (!el) continue;
      const c = track.muted ? null : clipAt(track, playhead);
      if (c) syncEl(el, c.media_id, sourceTimeAt(c, playhead), c.speed, censoring ? 0 : c.volume);
      else syncEl(el, null, 0, 1, 0);
    }
    // trigger bleep / sound-effect previews once when their window starts
    const ids = new Set(active.map(({ e }) => e.id));
    if (playing) for (const { e } of active) {
      if ((e.kind === "censor" || e.kind === "sfx") && e.sound && e.sound !== "mute" && !played.current.has(e.id)) {
        const a = new Audio(`/api/sounds/${e.sound}.wav`);
        a.volume = Math.min(1, e.volume);
        a.play().catch(() => {});
        sounds.current.set(e.id, a);
      }
    }
    for (const [id, a] of sounds.current) if (!ids.has(id) || !playing) { if (!a.paused && a.currentTime > 0.05 && !ids.has(id)) a.pause(); sounds.current.delete(id); }
    played.current = ids;
  }, [playhead, playing, timeline]);

  const step = (frames: number) => { setPlaying(false); setPlayhead(Math.max(0, Math.min(duration, playhead + frames / output.fps))); };
  const ar = output.width / output.height;

  return (
    <div className="monitor">
      <div className="screen-wrap">
        <div className="screen" ref={screenRef} style={{ aspectRatio: `${ar}`, height: ar < 1 ? "100%" : undefined, width: ar >= 1 ? "100%" : undefined }}>
          <video ref={videoRef} muted playsInline preload="auto" style={{ visibility: hasPicture ? "visible" : "hidden",
            transform: `scale(${zoom}) translate(${shaking ? Math.sin(playhead * 61) * 1.2 : 0}%, ${shaking ? Math.cos(playhead * 47) * 1.2 : 0}%)`,
            transformOrigin: zoomFx ? `${zoomFx.x * 100}% ${zoomFx.y * 100}%` : "50% 50%" }}
            onError={() => setVideoError("This file can't play in the browser yet — a preview copy is being prepared. Export still uses the original.")}
            onLoadedData={() => setVideoError(null)} />
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
      </div>
      {timeline.tracks.filter((t) => t.kind === "audio").map((t) => (
        <audio key={t.id} ref={(el) => { audioRefs.current[t.id] = el; }} preload="auto" />
      ))}
      <div className="transport">
        <button className="btn icon ghost" title="Go to start (Home)" onClick={() => { setPlaying(false); setPlayhead(0); }}><Icon name="start" /></button>
        <button className="btn icon ghost" title="Previous frame (←)" onClick={() => step(-1)}><Icon name="prev" /></button>
        <button className="btn icon" title="Play / pause (Space)" onClick={() => setPlaying(!playing)} disabled={duration <= 0}>
          <Icon name={playing ? "pause" : "play"} />
        </button>
        <button className="btn icon ghost" title="Next frame (→)" onClick={() => step(1)}><Icon name="next" /></button>
        <button className="btn icon ghost" title="Go to end (End)" onClick={() => { setPlaying(false); setPlayhead(duration); }}><Icon name="end" /></button>
        <span className="tc">{fmtTime(playhead)}</span>
        <span className="muted mono" style={{ fontSize: 12 }}>/ {fmtTime(duration)}</span>
        <span className="spacer" />
        <span className="muted" style={{ fontSize: 11 }}>{output.width}×{output.height} · {output.fps} fps</span>
      </div>
    </div>
  );
}
