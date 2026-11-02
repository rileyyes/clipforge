import React, { useEffect, useRef, useState } from "react";
import { fmtTime, mediaUrl } from "../api";
import { clipAt, sourceTimeAt, timelineDuration, topVideoClipAt } from "../timeline/ops";
import type { MediaMap, OutputSettings, Timeline } from "../timeline/types";
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
export default function Monitor({ projectId, timeline, media, output, playhead, setPlayhead, playing, setPlaying }: {
  projectId: string; timeline: Timeline; media: MediaMap; output: OutputSettings;
  playhead: number; setPlayhead: (t: number) => void; playing: boolean; setPlaying: (p: boolean) => void;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const audioRefs = useRef<Record<string, HTMLAudioElement | null>>({});
  const clock = useRef<{ t0: number; p0: number } | null>(null);
  const [videoError, setVideoError] = useState<string | null>(null);
  const [hasPicture, setHasPicture] = useState(false);
  const duration = timelineDuration(timeline);
  const playheadRef = useRef(playhead);
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
    for (const track of timeline.tracks) {
      if (track.kind !== "audio") continue;
      const el = audioRefs.current[track.id];
      if (!el) continue;
      const c = track.muted ? null : clipAt(track, playhead);
      if (c) syncEl(el, c.media_id, sourceTimeAt(c, playhead), c.speed, c.volume);
      else syncEl(el, null, 0, 1, 0);
    }
  }, [playhead, playing, timeline]);

  const step = (frames: number) => { setPlaying(false); setPlayhead(Math.max(0, Math.min(duration, playhead + frames / output.fps))); };
  const ar = output.width / output.height;

  return (
    <div className="monitor">
      <div className="screen-wrap">
        <div className="screen" style={{ aspectRatio: `${ar}`, height: ar < 1 ? "100%" : undefined, width: ar >= 1 ? "100%" : undefined }}>
          <video ref={videoRef} muted playsInline preload="auto" style={{ visibility: hasPicture ? "visible" : "hidden" }}
            onError={() => setVideoError("This file can't play in the browser yet — a preview copy is being prepared. Export still uses the original.")}
            onLoadedData={() => setVideoError(null)} />
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
