import React, { useMemo, useRef, useState } from "react";
import { fmtTime, uploadMedia } from "../api";
import { parseTime } from "../timeline/effects";
import { addMusic, deleteClips, musicItems, MUSIC_DEFAULTS, setMusicVolume, videoEnd, type MusicOptions, type OpResult } from "../timeline/ops";
import type { AudioSettings, MediaMap, Timeline } from "../timeline/types";
import { Icon, useToast } from "./ui";

const SONG_TYPES = ".mp3,.m4a,.aac,.wav,.flac,.ogg,.opus,.mp4,.mov,.mkv,.webm";

/** Editor → Music: put your own song under the video for a stretch of time. */
export default function MusicSection({ projectId, timeline, media, playhead, seek, commit, audio, setAudio, onImported }: {
  projectId: string; timeline: Timeline; media: MediaMap; playhead: number; seek: (t: number) => void;
  commit: (r: OpResult, label: string, coalesce?: boolean) => boolean;
  audio: AudioSettings; setAudio: (a: AudioSettings, label: string) => void; onImported: () => void;
}) {
  const toast = useToast();
  const end = videoEnd(timeline);
  // songs first (audio files), then videos with sound
  const songs = useMemo(() => Object.values(media).filter((m) => m.has_audio)
    .sort((a, b) => (a.kind === b.kind ? a.original_name.localeCompare(b.original_name) : a.kind === "audio" ? -1 : 1)), [media]);
  const [songId, setSongId] = useState<string>("");
  const song = media[songId] ?? songs.find((m) => m.kind === "audio") ?? null;
  const [from, setFrom] = useState("0:00.00");
  const [to, setTo] = useState<string | null>(null);   // null = end of the video
  const [o, setO] = useState<MusicOptions>(MUSIC_DEFAULTS);
  const [uploading, setUploading] = useState<number | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const items = musicItems(timeline);

  const toText = to ?? fmtTime(end);
  const fromT = parseTime(from), toT = parseTime(toText);
  const add = () => {
    if (!song) return toast("Pick a song first (or import one)", true);
    if (fromT === null || toT === null) return toast("Type the times like 0:12 or 12.5", true);
    const r = addMusic(timeline, song, fromT, toT, o);
    if (commit(r, "Add music")) {
      const loops = (r.created?.length ?? 1);
      toast(`Added “${song.original_name}” from ${fmtTime(fromT)} to ${fmtTime(toT)}${loops > 1 ? ` (looped ${loops}×)` : ""}`);
    }
  };
  const importSong = async (f: File) => {
    setUploading(0);
    try {
      const r = await uploadMedia(projectId, f, (p) => setUploading(p));
      setSongId(r.media.id);
      onImported();
      toast(r.duplicate ? `“${f.name}” was already in this project` : `Imported “${f.name}”`);
    } catch (e: any) { toast(`Couldn't import ${f.name}: ${e.message}`, true); }
    finally { setUploading(null); }
  };

  return (
    <div className="insp-section" style={{ marginBottom: 0, display: "grid", gap: 8, gridTemplateColumns: "minmax(0, 1fr)", minWidth: 0 }} data-testid="music-section">
      <h3 style={{ margin: 0 }}>Background music</h3>
      <div className="dim" style={{ fontSize: 11 }}>Put your own song under the video for a stretch of time. It loops if the song is shorter and
        goes quieter while you talk. Use music you have the rights to — YouTube can flag copyrighted songs.</div>
      <div className="row" style={{ gap: 6 }}>
        <select aria-label="Song" value={song?.id ?? ""} onChange={(e) => setSongId(e.target.value)} style={{ flex: 1, minWidth: 0 }}>
          {!songs.length && <option value="">No songs yet — import one</option>}
          {songs.map((m) => <option key={m.id} value={m.id}>{m.kind === "audio" ? "♪ " : "▶ "}{m.original_name} ({fmtTime(m.duration)})</option>)}
        </select>
        <button className="btn sm ghost" disabled={uploading !== null} onClick={() => fileRef.current?.click()} title="Import a song from your computer">
          <Icon name="upload" size={13} />{uploading !== null ? `${Math.round(uploading * 100)}%` : "Import"}</button>
        <input ref={fileRef} type="file" accept={SONG_TYPES} hidden data-testid="song-input"
          onChange={(e) => { const f = e.target.files?.[0]; if (f) importSong(f); e.target.value = ""; }} />
      </div>
      <div className="music-times">
        <label className="field">From
          <div className="row" style={{ gap: 4 }}>
            <input aria-label="Music from" className="mono" value={from} onChange={(e) => setFrom(e.target.value)} style={{ width: 0, flex: 1 }} />
            <button className="btn xs ghost" title="Use the playhead" onClick={() => setFrom(fmtTime(playhead))}>Playhead</button>
          </div></label>
        <label className="field">To
          <div className="row" style={{ gap: 4 }}>
            <input aria-label="Music to" className="mono" value={toText} onChange={(e) => setTo(e.target.value)} style={{ width: 0, flex: 1 }} />
            <button className="btn xs ghost" title="Use the playhead" onClick={() => setTo(fmtTime(playhead))}>Playhead</button>
          </div></label>
      </div>
      <div className="row" style={{ gap: 4, flexWrap: "wrap" }}>
        <button className="btn xs ghost" onClick={() => { setFrom(fmtTime(0)); setTo(null); }}>Whole video ({fmtTime(end)})</button>
        <span className="dim" style={{ fontSize: 11 }}>
          {fromT !== null && toT !== null && toT > fromT ? `${fmtTime(toT - fromT)} of music` : "type times like 0:12 or 12.5"}
          {song && fromT !== null && toT !== null && toT - fromT > song.duration - o.songStart && o.loop ? " · the song will loop" : ""}
        </span>
      </div>
      <label className="field">Volume <span className="mono" style={{ color: "var(--text)" }}>{Math.round(o.volume * 100)}%</span>
        <input type="range" aria-label="Music volume" min={0} max={1.5} step={0.05} value={o.volume} onChange={(e) => setO({ ...o, volume: +e.target.value })} /></label>
      <div className="insp-grid">
        <label className="field">Fade in (s)<input type="number" min={0} max={10} step={0.5} value={o.fadeIn} onChange={(e) => setO({ ...o, fadeIn: Math.max(0, +e.target.value) })} /></label>
        <label className="field">Fade out (s)<input type="number" min={0} max={10} step={0.5} value={o.fadeOut} onChange={(e) => setO({ ...o, fadeOut: Math.max(0, +e.target.value) })} /></label>
        <label className="field" title="Skip the song's intro: start this many seconds into it">Start song at (s)
          <input type="number" min={0} step={1} value={o.songStart} onChange={(e) => setO({ ...o, songStart: Math.max(0, +e.target.value) })} /></label>
        <label className="row" style={{ fontSize: 12, alignSelf: "end" }}>
          <input type="checkbox" checked={o.loop} onChange={(e) => setO({ ...o, loop: e.target.checked })} />Loop if shorter</label>
      </div>
      <button className="btn primary" disabled={!song} onClick={add}><Icon name="music" size={14} />Add music</button>
      <label className="field">Lower the music while you talk
        <select aria-label="Ducking" value={audio.ducking} onChange={(e) => setAudio({ ...audio, ducking: e.target.value as AudioSettings["ducking"] }, "Ducking")}>
          <option value="off">Off</option><option value="light">A little</option><option value="medium">Medium</option><option value="strong">A lot</option>
        </select></label>

      <div style={{ display: "grid", gap: 4 }}>
        <div className="dim" style={{ fontSize: 11 }}>Music in this video{items.length ? ` (${items.length})` : ": none yet"}</div>
        {items.map((it) => {
          const ids = it.clips.map((c) => c.id);
          return (
            <div key={it.clips[0].id} className="music-item" data-testid="music-item">
              <div className="row" style={{ gap: 6, minWidth: 0 }}>
                <Icon name="music" size={13} />
                <span className="ellipsis" style={{ flex: 1, minWidth: 0, fontSize: 12 }} title={media[it.media_id]?.original_name}>{media[it.media_id]?.original_name ?? "missing song"}</span>
                <button className="btn xs ghost mono" title="Go there" onClick={() => seek(it.start)}>{fmtTime(it.start)}–{fmtTime(it.end)}</button>
                <button className="btn xs ghost" title="Remove this music" aria-label="Remove music"
                  onClick={() => commit(deleteClips(timeline, ids, false), "Remove music")}><Icon name="trash" size={12} /></button>
              </div>
              <div className="row" style={{ gap: 6 }}>
                <span className="dim" style={{ fontSize: 11 }}>{it.track.name}{it.clips.length > 1 ? ` · looped ${it.clips.length}×` : ""}</span>
                <input type="range" aria-label="Volume of this music" min={0} max={1.5} step={0.05} value={it.volume} style={{ flex: 1, minWidth: 0 }}
                  onChange={(e) => commit(setMusicVolume(timeline, ids, +e.target.value), "Music volume", true)} />
                <span className="mono dim" style={{ fontSize: 11, width: 34, textAlign: "right" }}>{Math.round(it.volume * 100)}%</span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
