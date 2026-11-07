import React, { useState } from "react";
import { ApiError } from "../api";
import { beatTimes, fitMusicToVideo, snapCutsToBeats, type OpResult } from "../timeline/ops";
import type { MediaMap, Timeline } from "../timeline/types";
import { Icon, useToast } from "./ui";

/** Editor → Beat: find the beat of your music, show it, cut on it. */
export default function BeatPanel({ projectId, timeline, media, commit, beats, setBeats, showBeats, setShowBeats, top }: {
  /** shown first (the background-music section) */
  top?: React.ReactNode;
  projectId: string; timeline: Timeline; media: MediaMap; commit: (r: OpResult, label: string) => boolean;
  beats: Record<string, { bpm: number; beats: number[] }>; setBeats: (b: Record<string, { bpm: number; beats: number[] }>) => void;
  showBeats: boolean; setShowBeats: (v: boolean) => void;
}) {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const [tol, setTol] = useState(0.25);
  const musicTracks = timeline.tracks.filter((t) => t.kind === "audio" && t.role === "music");
  const songs = [...new Set(musicTracks.flatMap((t) => t.clips.map((c) => c.media_id)))];
  const found = songs.filter((m) => beats[m]);
  const times = beatTimes(timeline, Object.fromEntries(Object.entries(beats).map(([k, v]) => [k, v.beats])));

  return (
    <div className="pane-body" style={{ display: "grid", gap: 12, alignContent: "start", gridTemplateColumns: "minmax(0, 1fr)" }} data-testid="beat-panel">
      {top}
      <div className="insp-section" style={{ marginBottom: 0 }}>
        <h3 style={{ margin: 0 }}>Beat sync</h3>
        {!songs.length ? (
          <div className="muted" style={{ fontSize: 12 }}>
            Import a song and put it on a music track (the audio track with ♪ — A2 by default). Then RJClip can find its beat
            and line your cuts up with it. Free music you're allowed to use on YouTube: YouTube Studio → <b>Audio Library</b>.
          </div>
        ) : (<>
          {songs.map((m) => (
            <div key={m} className="row" style={{ fontSize: 12, gap: 6 }}>
              <Icon name="music" size={13} /><span className="ellipsis grow">{media[m]?.original_name ?? "song"}</span>
              <span className="mono">{beats[m] ? (beats[m].bpm ? `${beats[m].bpm} BPM` : "no steady beat") : ""}</span>
            </div>
          ))}
          <button className="btn sm" disabled={busy} onClick={async () => {
            setBusy(true);
            try {
              const next = { ...beats };
              for (const m of songs) {
                const r = await fetch(`/api/projects/${projectId}/beats`, { method: "POST", headers: { "X-RJClip": "1", "Content-Type": "application/json" }, body: JSON.stringify({ media_id: m }) });
                const d = await r.json();
                if (!r.ok) throw new ApiError(d.error || "Couldn't find the beat", r.status);
                next[m] = { bpm: d.bpm, beats: d.beats };
              }
              setBeats(next); setShowBeats(true);
              toast("Beat found — the green marks on the timeline are the beats");
            } catch (e: any) { toast(e.message, true); } finally { setBusy(false); }
          }}><Icon name="wand" size={13} />{busy ? "Listening…" : found.length === songs.length ? "Find the beat again" : "Find the beat"}</button>
        </>)}
      </div>
      {found.length > 0 && (
        <div className="insp-section">
          <label className="row" style={{ fontSize: 12 }}><input type="checkbox" checked={showBeats} onChange={(e) => setShowBeats(e.target.checked)} />Show beats on the timeline ({times.length})</label>
          <label className="row" style={{ fontSize: 12 }}>Move a cut at most
            <select value={tol} onChange={(e) => setTol(+e.target.value)} aria-label="Snap distance">
              <option value={0.15}>0.15 s</option><option value={0.25}>0.25 s</option><option value={0.4}>0.4 s</option>
            </select></label>
          <button className="btn sm primary" onClick={() => {
            const r = snapCutsToBeats(timeline, times, media, tol);
            if (r.error !== undefined) return toast(r.error, true);
            if (commit(r, "Snap cuts to the beat")) toast(`${r.count} cut${r.count === 1 ? "" : "s"} moved onto the beat${r.skipped ? ` (${r.skipped} had no spare footage)` : ""} — Ctrl+Z to undo`);
          }}><Icon name="scissors" size={13} />Snap cuts to the beat</button>
          <div className="muted" style={{ fontSize: 11 }}>Each cut on V1 near a beat moves onto it: the clip before gets a bit longer or shorter, the next starts a bit later or earlier. Nothing else shifts.</div>
          <button className="btn sm" onClick={() => {
            const r = fitMusicToVideo(timeline);
            if (r.error !== undefined) return toast(r.error, true);
            if (commit(r, "End music with the video")) toast("The music now ends with the video, fading out");
          }}><Icon name="fit" size={13} />End the music with the video</button>
        </div>
      )}
    </div>
  );
}
