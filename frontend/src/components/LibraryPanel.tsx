import React, { useEffect, useRef, useState } from "react";
import { library, type LibraryItem } from "../api";
import { Icon, PromptModal, useToast } from "./ui";

const MAX_RECORD_S = 30;

/** Pick a recording format this browser supports (Chrome/Edge: WebM Opus, Firefox: Ogg, Safari: MP4). */
function recorderType(): string | undefined {
  const types = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus", "audio/mp4"];
  return types.find((t) => typeof MediaRecorder !== "undefined" && MediaRecorder.isTypeSupported?.(t));
}

/**
 * "My sounds & images": your own library shared by every project. Record from the mic
 * or import files; then use them as the bleep sound, drop them at the playhead as a
 * sound effect, or add images as pop-ups.
 */
export default function LibraryPanel({ onUseSound, onAddSound, onAddImage, bleepSound, onChanged }: {
  onChanged?: () => void;                       // the library changed (others may list it)
  onUseSound: (s: LibraryItem) => void;         // make it the bleep sound
  onAddSound: (s: LibraryItem) => void;         // sound effect at the playhead
  onAddImage: (i: LibraryItem) => void;         // image pop-up at the playhead
  bleepSound?: string | null;
}) {
  const [items, setItems] = useState<{ sounds: LibraryItem[]; images: LibraryItem[] } | null>(null);
  const [rec, setRec] = useState<null | { started: number; level: number }>(null);
  const [take, setTake] = useState<null | { blob: Blob; url: string }>(null);
  const [busy, setBusy] = useState(false);
  const [renaming, setRenaming] = useState<LibraryItem | null>(null);
  const [tagging, setTagging] = useState<LibraryItem | null>(null);
  const [tick, setTick] = useState(0);
  const recorder = useRef<{ mr: MediaRecorder; stream: MediaStream; ctx?: AudioContext; raf: number; timer: any } | null>(null);
  const soundFile = useRef<HTMLInputElement>(null);
  const imageFile = useRef<HTMLInputElement>(null);
  const playing = useRef<HTMLAudioElement | null>(null);
  const toast = useToast();

  const load = () => library.list().then((r) => { setItems(r); onChanged?.(); }).catch((e) => toast(e.message, true));
  useEffect(() => { load(); return () => stopStream(); }, []);
  useEffect(() => { if (!rec) return; const t = setInterval(() => setTick((n) => n + 1), 200); return () => clearInterval(t); }, [!!rec]);

  const play = (url: string) => {
    playing.current?.pause();
    const a = new Audio(url);
    playing.current = a;
    a.play().catch(() => {});
  };

  // ---------------------------------------------------------------- recording
  function stopStream() {
    const r = recorder.current;
    if (!r) return;
    cancelAnimationFrame(r.raf);
    clearTimeout(r.timer);
    r.stream.getTracks().forEach((t) => t.stop());
    r.ctx?.close().catch(() => {});
    recorder.current = null;
  }

  const startRecording = async () => {
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      return toast("This browser can't record audio. Try Chrome, Edge or Firefox.", true);
    }
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: false, noiseSuppression: true, autoGainControl: true } });
    } catch (e: any) {
      return toast(e?.name === "NotAllowedError" ? "Microphone blocked — allow it with the icon in the address bar, then try again."
        : e?.name === "NotFoundError" ? "No microphone found." : `Couldn't start the microphone: ${e?.message ?? e}`, true);
    }
    const type = recorderType();
    const mr = new MediaRecorder(stream, type ? { mimeType: type } : undefined);
    const chunks: Blob[] = [];
    mr.ondataavailable = (ev) => { if (ev.data.size) chunks.push(ev.data); };
    mr.onstop = () => {
      stopStream();
      setRec(null);
      const blob = new Blob(chunks, { type: mr.mimeType || type || "audio/webm" });
      if (blob.size < 200) { toast("Nothing was recorded.", true); return; }
      setTake((old) => { if (old) URL.revokeObjectURL(old.url); return { blob, url: URL.createObjectURL(blob) }; });
    };
    // live input level so you can see the mic is working
    let ctx: AudioContext | undefined, raf = 0;
    try {
      ctx = new AudioContext();
      const an = ctx.createAnalyser();
      an.fftSize = 512;
      ctx.createMediaStreamSource(stream).connect(an);
      const buf = new Float32Array(an.fftSize);
      const loop = () => {
        an.getFloatTimeDomainData(buf);
        let p = 0;
        for (const v of buf) p = Math.max(p, Math.abs(v));
        setRec((r) => (r ? { ...r, level: p } : r));
        raf = requestAnimationFrame(loop);
        if (recorder.current) recorder.current.raf = raf;
      };
      raf = requestAnimationFrame(loop);
    } catch { /* level meter is optional */ }
    const timer = setTimeout(() => mr.state === "recording" && mr.stop(), MAX_RECORD_S * 1000);
    recorder.current = { mr, stream, ctx, raf, timer };
    mr.start(250);
    setTake(null);
    setRec({ started: performance.now(), level: 0 });
  };
  const stopRecording = () => { const r = recorder.current; if (r && r.mr.state === "recording") r.mr.stop(); };

  const saveTake = async (name: string) => {
    if (!take) return;
    setBusy(true);
    try {
      const item = await library.addSound(take.blob, name, true);
      URL.revokeObjectURL(take.url);
      setTake(null);
      toast(`Saved “${item.name}” (${item.duration?.toFixed(1)} s) to your library`);
      load();
    } catch (e: any) { toast(e.message, true); } finally { setBusy(false); }
  };

  // ---------------------------------------------------------------- import
  const importFiles = async (files: FileList | null, kind: "sound" | "image") => {
    if (!files?.length) return;
    setBusy(true);
    let ok = 0;
    for (const f of Array.from(files)) {
      try { await (kind === "sound" ? library.addSound(f, f.name, false) : library.addImage(f, f.name)); ok++; }
      catch (e: any) { toast(`${f.name}: ${e.message}`, true); }
    }
    setBusy(false);
    if (ok) toast(`Added ${ok} ${kind}${ok === 1 ? "" : "s"} to your library`);
    load();
  };

  const remove = async (it: LibraryItem) => {
    if (!confirm(`Delete “${it.name}” from your library? Edits that already use it keep working.`)) return;
    try { await library.remove(it.kind, it.id); load(); } catch (e: any) { toast(e.message, true); }
  };

  const secs = rec ? (performance.now() - rec.started) / 1000 : 0;
  void tick;
  return (
    <div className="insp-section" data-testid="library">
      <h3 style={{ margin: 0 }}>My sounds & images</h3>
      <div className="dim" style={{ fontSize: 11 }}>Your own library, shared by all projects. Record a sound with your mic or import files (MP3, WAV, M4A, OGG — or a video, its audio is used; images PNG/JPG/WebP/GIF).</div>

      {/* recorder */}
      <div className="row" style={{ gap: 6, flexWrap: "wrap" }}>
        {!rec ? (
          <button className="btn sm" disabled={busy} onClick={startRecording} data-testid="record"><span className="rec-dot" />Record sound</button>
        ) : (
          <button className="btn sm danger" onClick={stopRecording} data-testid="stop"><span className="rec-dot on" />Stop · {secs.toFixed(1)} s</button>
        )}
        {rec && <div className="rec-level" title="Microphone level"><div style={{ width: `${Math.min(100, rec.level * 140)}%` }} /></div>}
        <button className="btn sm ghost" disabled={busy || !!rec} onClick={() => soundFile.current?.click()}><Icon name="upload" size={13} />Import sound</button>
        <button className="btn sm ghost" disabled={busy || !!rec} onClick={() => imageFile.current?.click()}><Icon name="image" size={13} />Import image</button>
        <input ref={soundFile} type="file" multiple hidden accept="audio/*,video/*,.mp3,.wav,.m4a,.ogg,.webm,.flac,.aac"
          onChange={(e) => { importFiles(e.target.files, "sound"); e.target.value = ""; }} />
        <input ref={imageFile} type="file" multiple hidden accept="image/png,image/jpeg,image/webp,image/gif"
          onChange={(e) => { importFiles(e.target.files, "image"); e.target.value = ""; }} />
      </div>
      {rec && <div className="dim" style={{ fontSize: 11 }}>Recording… stops by itself after {MAX_RECORD_S} s. Silence at the start and end is trimmed.</div>}
      {take && (
        <TakeReview url={take.url} busy={busy} onSave={saveTake} onDiscard={() => { URL.revokeObjectURL(take.url); setTake(null); }} />
      )}

      {/* sounds */}
      {items && items.sounds.length > 0 && <div className="lib-head">Sounds</div>}
      {items?.sounds.map((s) => (
        <div key={s.id} className="lib-row" data-testid="lib-sound">
          <div className="lib-line">
            <button className="btn icon ghost xs" title="Play" onClick={() => play(library.url("sound", s.id))}><Icon name="play" size={12} /></button>
            <span className="ellipsis grow" title={s.name}>{s.name}</span>
            <span className="mono dim" style={{ fontSize: 10 }}>{(s.duration ?? 0).toFixed(1)}s</span>
            {s.source === "recorded" && <span className="chip" title="Recorded with your mic">mic</span>}
          </div>
          {!!s.tags?.length && <div className="dim ellipsis" style={{ fontSize: 10 }}>keywords: {s.tags.join(", ")}</div>}
          <div className="lib-line">
          <button className={"btn xs" + (bleepSound === s.id ? " on" : " ghost")} title="Use this as the sound for bleeping swears" onClick={() => onUseSound(s)}>Bleep</button>
          <button className="btn xs ghost" title="Add at the playhead as a sound effect" onClick={() => onAddSound(s)}><Icon name="plus" size={11} />Add</button>
          <button className="btn icon ghost xs" title="Rename" onClick={() => setRenaming(s)}><Icon name="pencil" size={11} /></button>
          <button className="btn xs ghost" title="Keywords: when you say one, RJClip suggests this sound there" onClick={() => setTagging(s)}>#</button>
          <span className="spacer" />
          <button className="btn icon ghost xs" title="Delete from library" onClick={() => remove(s)}><Icon name="trash" size={11} /></button>
          </div>
        </div>
      ))}

      {/* images */}
      {items && items.images.length > 0 && <div className="lib-head">Images</div>}
      {items && items.images.length > 0 && (
        <div className="lib-images">
          {items.images.map((i) => (
            <div key={i.id} className="lib-image" data-testid="lib-image" title={i.name}>
              <img src={library.url("image", i.id)} alt={i.name} />
              <div className="row" style={{ gap: 2 }}>
                <button className="btn xs" onClick={() => onAddImage(i)} title="Add at the playhead as a pop-up"><Icon name="plus" size={11} />Add</button>
                <span className="spacer" />
                <button className="btn icon ghost xs" title="Rename" onClick={() => setRenaming(i)}><Icon name="pencil" size={11} /></button>
                <button className="btn xs ghost" title={`Keywords${i.tags?.length ? ": " + i.tags.join(", ") : ""} (when you say one, RJClip suggests this image there)`} onClick={() => setTagging(i)}>#</button>
                <button className="btn icon ghost xs" title="Delete from library" onClick={() => remove(i)}><Icon name="trash" size={11} /></button>
              </div>
            </div>
          ))}
        </div>
      )}
      {items && !items.sounds.length && !items.images.length && !take && <div className="muted" style={{ fontSize: 12 }}>Nothing here yet.</div>}

      {tagging && (
        <PromptModal title={`Keywords for “${tagging.name}”`} label="When you say one of these words, RJClip suggests it there (comma separated). Its name counts too."
          initial={(tagging.tags ?? []).join(", ")} confirm="Save" onClose={() => setTagging(null)}
          onSubmit={async (v) => {
            const it = tagging; setTagging(null);
            try { await library.setTags(it.kind, it.id, v.split(",").map((t) => t.trim()).filter(Boolean)); load(); } catch (e: any) { toast(e.message, true); }
          }} />
      )}
      {renaming && (
        <PromptModal title={`Rename ${renaming.kind}`} label="Name" initial={renaming.name} confirm="Rename" onClose={() => setRenaming(null)}
          onSubmit={async (v) => {
            const it = renaming; setRenaming(null);
            try { await library.rename(it.kind, it.id, v.slice(0, 60)); load(); } catch (e: any) { toast(e.message, true); }
          }} />
      )}
    </div>
  );
}

function TakeReview({ url, busy, onSave, onDiscard }: { url: string; busy: boolean; onSave: (name: string) => void; onDiscard: () => void }) {
  const [name, setName] = useState(`Recording ${new Date().toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}`);
  return (
    <div className="take" data-testid="take">
      <audio src={url} controls style={{ width: "100%", height: 32 }} />
      <div className="row" style={{ gap: 4 }}>
        <input type="text" value={name} maxLength={60} aria-label="Sound name" onChange={(e) => setName(e.target.value)} style={{ flex: 1, minWidth: 0 }} />
        <button className="btn sm primary" disabled={busy || !name.trim()} onClick={() => onSave(name.trim())}>Save</button>
        <button className="btn sm ghost" disabled={busy} onClick={onDiscard}>Discard</button>
      </div>
    </div>
  );
}

