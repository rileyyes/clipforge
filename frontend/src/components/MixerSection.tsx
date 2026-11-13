import React from "react";
import type { OpResult } from "../timeline/ops";
import { anySolo, clampFx, fmtDb, MAX_FX_VOLUME, MAX_TRACK_VOLUME, resetMix, setTrackMix, trackGain } from "../timeline/phase20";
import type { AudioSettings, Timeline } from "../timeline/types";

const ROLE: Record<string, string> = { dialogue: "recording", music: "music", narration: "voice-over" };

/** Editor → Music → Sound mixer (Phase 20): one level per sound track (movie / game sound,
 *  music, your voice), mute and solo, plus one level for all sound effects and bleeps.
 *  The preview plays it this way and the export mixes it the same way. */
export default function MixerSection({ timeline, commit, audio, setAudio }: {
  timeline: Timeline; commit: (r: OpResult, label: string, coalesce?: boolean) => boolean;
  audio: AudioSettings; setAudio: (a: AudioSettings, label: string) => void;
}) {
  const tracks = timeline.tracks.filter((t) => t.kind === "audio");
  const solo = anySolo(timeline);
  const fx = audio.fx_volume ?? 1;
  const changed = tracks.some((t) => (t.volume ?? 1) !== 1 || t.solo);
  return (
    <div className="insp-section" style={{ marginBottom: 0, display: "grid", gap: 6 }} data-testid="mixer">
      <div className="row"><h3 style={{ margin: 0 }}>Sound mixer</h3><span className="spacer" />
        <button className="btn xs ghost" disabled={!changed} title="Every track back to 100 %, no solo"
          onClick={() => commit(resetMix(timeline), "Reset mixer")}>Reset</button></div>
      <div className="dim" style={{ fontSize: 11 }}>Balance the movie or game sound, your music and your voice. Per-clip volume and ◆ keyframes still work on top of this.</div>
      {tracks.map((t) => {
        const v = t.volume ?? 1, heard = trackGain(timeline, t) > 0;
        return (
          <div key={t.id} className="mixer-row" data-testid="mixer-row" data-track={t.name} data-heard={heard ? "1" : "0"}
            style={{ display: "grid", gap: 2, opacity: heard ? 1 : 0.55 }}>
            <div className="row" style={{ gap: 6, minWidth: 0 }}>
              <strong style={{ fontSize: 12 }}>{t.name}</strong>
              <span className="dim ellipsis" style={{ fontSize: 11, flex: 1, minWidth: 0 }}>{ROLE[t.role ?? "dialogue"]} · {t.clips.length} clip{t.clips.length === 1 ? "" : "s"}</span>
              <button className={"btn xs" + (t.muted ? " primary" : " ghost")} aria-pressed={t.muted} aria-label={`Mute ${t.name}`} title="Mute"
                onClick={() => commit(setTrackMix(timeline, t.id, { muted: !t.muted }), t.muted ? "Unmute track" : "Mute track")}>M</button>
              <button className={"btn xs" + (t.solo ? " primary" : " ghost")} aria-pressed={!!t.solo} aria-label={`Solo ${t.name}`}
                title="Solo: hear only the solo tracks (the export too)"
                onClick={() => commit(setTrackMix(timeline, t.id, { solo: !t.solo }), t.solo ? "Unsolo track" : "Solo track")}>S</button>
            </div>
            <div className="row" style={{ gap: 6 }}>
              <input type="range" aria-label={`Volume of ${t.name}`} min={0} max={MAX_TRACK_VOLUME} step={0.01} value={v} style={{ flex: 1, minWidth: 0 }}
                onChange={(e) => commit(setTrackMix(timeline, t.id, { volume: +e.target.value }), "Track volume", true)}
                onDoubleClick={() => commit(setTrackMix(timeline, t.id, { volume: 1 }), "Track volume")} />
              <span className="mono dim" style={{ fontSize: 11, width: 92, flex: "none", whiteSpace: "nowrap", textAlign: "right" }} data-testid="mixer-value">{Math.round(v * 100)}% · {fmtDb(v)}</span>
            </div>
          </div>
        );
      })}
      {!tracks.length && <div className="dim" style={{ fontSize: 12 }}>No sound tracks yet.</div>}
      <div style={{ display: "grid", gap: 2 }}>
        <span style={{ fontSize: 12 }}>Sound effects &amp; bleeps</span>
        <div className="row" style={{ gap: 6 }}>
          <input type="range" aria-label="Volume of sound effects" min={0} max={MAX_FX_VOLUME} step={0.01} value={fx} style={{ flex: 1, minWidth: 0 }}
            onChange={(e) => setAudio({ ...audio, fx_volume: clampFx(+e.target.value) }, "Effects volume")}
            onDoubleClick={() => setAudio({ ...audio, fx_volume: 1 }, "Effects volume")} />
          <span className="mono dim" style={{ fontSize: 11, width: 92, flex: "none", whiteSpace: "nowrap", textAlign: "right" }}>{Math.round(fx * 100)}% · {fmtDb(fx)}</span>
        </div>
      </div>
      {solo && <div className="chip warn" style={{ justifySelf: "start", fontSize: 11, whiteSpace: "normal", height: "auto", lineHeight: 1.35, padding: "3px 8px" }}>Solo is on: only solo tracks are heard, in the export too</div>}
      {audio.normalize && <div className="dim" style={{ fontSize: 11 }}>“Normalise loudness” (Effects tab) is on, so the finished video is brought to that level overall; the mixer sets the balance between the tracks.</div>}
      <div className="dim" style={{ fontSize: 11 }}>Double-click a slider for 100 %.</div>
    </div>
  );
}
