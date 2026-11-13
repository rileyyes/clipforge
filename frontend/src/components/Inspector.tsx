import React, { useEffect, useState } from "react";
import { fmtTime } from "../api";
import { clipDuration, clipEnd, findClip, type ClipPatch } from "../timeline/ops";
import { keyframeNear, NO_COLOR, NO_CROP, propAt, removeKeyframe, setKeyframe, sourceAt, staticValue } from "../timeline/keyframes";
import { LOOKS, TRANSITIONS, type Clip, type ColorAdjust, type KfProp, type Keyframe, type MediaMap, type Timeline, type Transition } from "../timeline/types";
import { Icon } from "./ui";

type Patch = (p: ClipPatch, label: string) => void;

/** A property that can be keyframed: slider + value, ◆ to add/remove a keyframe at the playhead,
 *  ‹ › to jump between keyframes. With keyframes, changing the value sets one at the playhead. */
function KfControl({ clip, prop, label, min, max, step, fmt, playhead, seek, patch }: {
  clip: Clip; prop: KfProp; label: string; min: number; max: number; step: number; fmt: (v: number) => string;
  playhead: number; seek: (t: number) => void; patch: Patch;
}) {
  const kfs = clip.keyframes?.[prop] ?? [];
  const inside = playhead >= clip.start - 1e-6 && playhead <= clipEnd(clip) + 1e-6;
  const st = sourceAt(clip, playhead);
  const value = inside ? propAt(clip, prop, playhead) : kfs.length ? kfs[0].v : staticValue(clip, prop);
  const here = inside ? keyframeNear(kfs, st) : undefined;
  const animated = kfs.length > 0;
  const setStatic = (v: number) => patch(prop === "volume" ? { volume: v } : { transform: { [prop]: v } }, `Change ${label.toLowerCase()}`);
  const setKf = (list: Keyframe[], lbl: string) => patch({ keyframes: { [prop]: list } }, lbl);
  const change = (v: number) => (animated ? (inside && setKf(setKeyframe(kfs, prop, st, v), `Keyframe ${label.toLowerCase()}`)) : setStatic(v));
  const tl = (k: Keyframe) => clip.start + (k.t - clip.source_in) / clip.speed;
  const visible = kfs.filter((k) => k.t >= clip.source_in - 1e-6 && k.t <= clip.source_out + 1e-6);
  const prev = [...visible].reverse().find((k) => tl(k) < playhead - 1e-3);
  const next = visible.find((k) => tl(k) > playhead + 1e-3);
  return (
    <div className="kf-row" data-testid={`kf-${prop}`}>
      <div className="row" style={{ gap: 4 }}>
        <span style={{ fontSize: 12 }}>{label}</span>
        <span className="mono" style={{ fontSize: 12, color: "var(--text)" }}>{fmt(value)}</span>
        <span className="spacer" />
        {animated && <button className="btn icon ghost xs" title="Previous keyframe" disabled={!prev} onClick={() => prev && seek(tl(prev))}><Icon name="prev" size={12} /></button>}
        <button className={"btn icon xs kf-btn" + (here ? " on" : animated ? " some" : " ghost")} disabled={!inside}
          title={!inside ? "Move the playhead over this clip to add keyframes" : here ? "Remove the keyframe here" : "Add a keyframe here"}
          onClick={() => (here ? setKf(removeKeyframe(kfs, here.t), `Remove ${label.toLowerCase()} keyframe`)
            : setKf(setKeyframe(kfs, prop, st, value), `Add ${label.toLowerCase()} keyframe`))}>◆</button>
        {animated && <button className="btn icon ghost xs" title="Next keyframe" disabled={!next} onClick={() => next && seek(tl(next))}><Icon name="next" size={12} /></button>}
      </div>
      <input type="range" min={min} max={max} step={step} value={Math.max(min, Math.min(max, value))} disabled={animated && !inside}
        aria-label={label} onChange={(e) => change(+e.target.value)} />
      {here && kfs.indexOf(here) < kfs.length - 1 && (
        <div className="row" style={{ gap: 4, fontSize: 11 }}>
          <span className="dim">To next keyframe</span>
          <select value={here.ease ?? "linear"} onChange={(e) => setKf(kfs.map((k) => (k === here ? { ...k, ease: e.target.value as Keyframe["ease"] } : k)), "Keyframe easing")}>
            <option value="linear">Linear</option><option value="ease">Ease in/out</option><option value="hold">Hold</option>
          </select>
        </div>
      )}
      {animated && (
        <div className="row dim" style={{ fontSize: 11, gap: 4 }}>
          {kfs.length} keyframe{kfs.length === 1 ? "" : "s"}<span className="spacer" />
          <button className="btn xs ghost" onClick={() => setKf([], `Clear ${label.toLowerCase()} keyframes`)}>Clear</button>
        </div>
      )}
    </div>
  );
}

function Slider({ label, value, min, max, step, fmt, onChange }: { label: string; value: number; min: number; max: number; step: number; fmt: (v: number) => string; onChange: (v: number) => void }) {
  return (
    <label className="field" style={{ gap: 2 }}><span className="row" style={{ gap: 4 }}>{label}<span className="spacer" /><span className="mono" style={{ color: "var(--text)" }}>{fmt(value)}</span></span>
      <input type="range" min={min} max={max} step={step} value={value} aria-label={label} onChange={(e) => onChange(+e.target.value)} />
    </label>
  );
}
const pct = (v: number) => `${Math.round(v * 100)}%`;
const signed = (v: number) => `${v > 0 ? "+" : ""}${Math.round(v * 100)}`;

/** Number field that commits on Enter/blur (so typing "1." doesn't fight the state). */
function Num({ label, value, onCommit, step = 0.01, min, max, suffix }: {
  label: string; value: number; onCommit: (v: number) => void; step?: number; min?: number; max?: number; suffix?: string;
}) {
  const [v, setV] = useState(String(value));
  useEffect(() => setV(String(Math.round(value * 1000) / 1000)), [value]);
  const commit = () => {
    const n = parseFloat(v);
    if (isFinite(n) && n !== value) onCommit(n); else setV(String(Math.round(value * 1000) / 1000));
  };
  return (
    <label className="field"><span>{label}{suffix && <span className="dim"> ({suffix})</span>}</span>
      <input type="number" step={step} min={min} max={max} value={v} onChange={(e) => setV(e.target.value)}
        onBlur={commit} onKeyDown={(e) => { if (e.key === "Enter") { commit(); (e.target as HTMLInputElement).blur(); } }} />
    </label>
  );
}

export default function Inspector({ timeline, media, selection, onPatch, onTrim, onMove, onTransition, onFades, playhead, seek, extra }: {
  /** more tools shown at the end (Phase 15: freeze, reverse, ramps, layouts, green screen) */
  extra?: React.ReactNode;
  timeline: Timeline; media: MediaMap; selection: string[]; playhead: number; seek: (t: number) => void;
  onPatch: (id: string, p: ClipPatch, label: string) => void;
  onTrim: (id: string, edge: "start" | "end", t: number) => void;
  onMove: (id: string, start: number) => void;
  onTransition: (id: string, tr: Transition | null) => void;
  onFades: (id: string, fadeIn: number, fadeOut: number) => void;
}) {
  const ref = selection.length === 1 ? findClip(timeline, selection[0]) : null;
  if (!ref) {
    return (
      <div style={{ display: "contents" }}>
        <div className="pane-body muted" style={{ fontSize: 12 }}>
          {selection.length > 1 ? `${selection.length} clips selected.` : "Select a clip to see and edit its properties."}
          <div style={{ marginTop: 18, display: "grid", gap: 6 }}>
            <div className="dim">Shortcuts</div>
            {[["Space", "Play / pause"], ["S", "Split at playhead"], ["Del", "Delete"], ["Shift+Del", "Ripple delete"],
              ["Ctrl+D", "Duplicate"], ["Ctrl+Z / Ctrl+Shift+Z", "Undo / redo"], ["← →", "Step one frame"], ["N", "Toggle snapping"],
              ["Ctrl+L", "Link / unlink picture and sound"], ["M", "Add a marker"], ["?", "All shortcuts"]].map(([k, d]) => (
              <div key={k} className="row"><span className="kbd">{k}</span><span>{d}</span></div>
            ))}
          </div>
          {extra && <div style={{ marginTop: 18, color: "var(--text)" }}>{extra}</div>}
        </div>
      </div>
    );
  }
  const { clip, track } = ref;
  const m = media[clip.media_id];
  const patch: Patch = (p, label) => onPatch(clip.id, p, label);
  const kfp = { clip, playhead, seek, patch };
  const crop = clip.crop ?? NO_CROP;
  const color = clip.color ?? NO_COLOR;
  const setColor = (c: Partial<ColorAdjust>, label: string) => patch({ color: { ...color, ...c } }, label);
  return (
    <div style={{ display: "contents" }}>
      <div className="pane-body">
        <div className="row" style={{ marginBottom: 6 }}><strong style={{ fontSize: 12 }}>Clip</strong><span className={"chip " + (track.kind === "video" ? "run" : "ok")}>{track.name}</span></div>
        <div className="insp-section">
          <div className="ellipsis" style={{ fontWeight: 600 }} title={m?.original_name}>{m?.original_name ?? "missing media"}</div>
          <dl className="kv">
            <dt>On timeline</dt><dd className="mono">{fmtTime(clip.start)} → {fmtTime(clipEnd(clip))}</dd>
            <dt>Duration</dt><dd className="mono">{fmtTime(clipDuration(clip))}</dd>
            <dt>From source</dt><dd className="mono">{fmtTime(clip.source_in)} → {fmtTime(clip.source_out)}</dd>
            {clip.link_id && <><dt>Linked</dt><dd>edits move picture and sound together</dd></>}
          </dl>
          {track.locked && <span className="chip warn">Track is locked</span>}
        </div>

        <div className="insp-section">
          <h3 style={{ margin: 0 }}>Timing</h3>
          <div className="insp-grid">
            <Num label="Start" suffix="s" value={clip.start} min={0} onCommit={(v) => onMove(clip.id, v)} />
            <Num label="Speed" suffix="×" value={clip.speed} step={0.05} min={0.25} max={4}
              onCommit={(v) => onPatch(clip.id, { speed: v }, "Change speed")} />
            <Num label="Source in" suffix="s" value={clip.source_in} min={0}
              onCommit={(v) => onTrim(clip.id, "start", clip.start + (v - clip.source_in) / clip.speed)} />
            <Num label="Source out" suffix="s" value={clip.source_out} max={m?.duration}
              onCommit={(v) => onTrim(clip.id, "end", clipEnd(clip) + (v - clip.source_out) / clip.speed)} />
          </div>
        </div>

        {(track.kind === "audio" || timeline.tracks.find((t) => t.kind === "video" && !t.hidden)?.id === track.id) && (
          <div className="insp-section">
            <h3 style={{ margin: 0 }}>{track.kind === "video" ? "Transition & fades" : "Fades"}</h3>
            {track.kind === "video" && (
              <div className="insp-grid">
                <label className="field">Transition in
                  <select value={clip.transition_in?.kind ?? "none"} onChange={(e) => onTransition(clip.id, e.target.value === "none" ? null
                    : { kind: e.target.value as Transition["kind"], duration: clip.transition_in?.duration ?? 0.5 })}>
                    <option value="none">None (cut)</option>
                    {TRANSITIONS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                  </select>
                </label>
                {clip.transition_in && <Num label="Length" suffix="s" step={0.1} min={0.1} max={3} value={clip.transition_in.duration}
                  onCommit={(v) => onTransition(clip.id, { ...clip.transition_in!, duration: Math.max(0.1, Math.min(3, v)) })} />}
              </div>
            )}
            <div className="insp-grid">
              <Num label={track.kind === "video" ? "Fade from black" : "Fade in"} suffix="s" step={0.1} min={0} max={10} value={clip.fade_in ?? 0}
                onCommit={(v) => onFades(clip.id, v, clip.fade_out ?? 0)} />
              <Num label={track.kind === "video" ? "Fade to black" : "Fade out"} suffix="s" step={0.1} min={0} max={10} value={clip.fade_out ?? 0}
                onCommit={(v) => onFades(clip.id, clip.fade_in ?? 0, v)} />
            </div>
            <div className="dim" style={{ fontSize: 11 }}>{track.kind === "video"
              ? "A transition blends from the clip right before this one; with no clip right before, it fades up from black. Shown in the export (the preview shows a cut). Linked audio crossfades too."
              : "Volume fades — great for background music. Applied in the export."}</div>
          </div>
        )}

        {track.kind === "audio" && (
          <div className="insp-section">
            <h3 style={{ margin: 0 }}>Audio</h3>
            <KfControl {...kfp} prop="volume" label="Volume" min={0} max={2} step={0.01} fmt={pct} />
            <div className="dim" style={{ fontSize: 11 }}>Use ◆ keyframes to raise or lower the volume over time (e.g. music under talking).</div>
          </div>
        )}

        {track.kind === "video" && (
          <>
            <div className="insp-section" data-testid="transform">
              <div className="row"><h3 style={{ margin: 0 }}>Transform</h3><span className="spacer" />
                <button className="btn xs ghost" onClick={() => patch({ transform: { x: 0, y: 0, scale: 1, rotation: 0, opacity: 1 },
                  keyframes: { x: [], y: [], scale: [], rotation: [], opacity: [] } }, "Reset transform")}>Reset</button></div>
              <KfControl {...kfp} prop="scale" label="Scale" min={0.1} max={3} step={0.01} fmt={pct} />
              <KfControl {...kfp} prop="x" label="Position X" min={-2000} max={2000} step={1} fmt={(v) => `${Math.round(v)} px`} />
              <KfControl {...kfp} prop="y" label="Position Y" min={-2000} max={2000} step={1} fmt={(v) => `${Math.round(v)} px`} />
              <KfControl {...kfp} prop="rotation" label="Rotation" min={-180} max={180} step={1} fmt={(v) => `${Math.round(v)}°`} />
              <KfControl {...kfp} prop="opacity" label="Opacity" min={0} max={1} step={0.01} fmt={pct} />
              <div className="dim" style={{ fontSize: 11 }}>◆ adds a keyframe at the playhead; add two with different values to animate (e.g. a slow zoom). Keyframes stick to the footage, so trimming keeps them in place.</div>
            </div>

            <div className="insp-section" data-testid="crop">
              <div className="row"><h3 style={{ margin: 0 }}>Crop</h3><span className="spacer" />
                <button className="btn xs ghost" onClick={() => patch({ crop: NO_CROP }, "Reset crop")}>Reset</button></div>
              <div className="insp-grid">
                {(["left", "right", "top", "bottom"] as const).map((side) => {
                  const other = side === "left" ? "right" : side === "right" ? "left" : side === "top" ? "bottom" : "top";
                  return <Slider key={side} label={side[0].toUpperCase() + side.slice(1)} value={crop[side]} min={0} max={0.9 - crop[other]} step={0.005} fmt={pct}
                    onChange={(v) => patch({ crop: { ...crop, [side]: Math.min(v, 0.9 - crop[other]) } }, "Crop")} />;
                })}
              </div>
            </div>

            <div className="insp-section" data-testid="color">
              <div className="row"><h3 style={{ margin: 0 }}>Colour</h3><span className="spacer" />
                <button className="btn xs ghost" onClick={() => patch({ color: NO_COLOR }, "Reset colour")}>Reset</button></div>
              <label className="field">Look
                <select value={color.look} aria-label="Look" onChange={(e) => setColor({ look: e.target.value as ColorAdjust["look"] }, "Look")}>
                  {LOOKS.map((l) => <option key={l} value={l}>{{ none: "None", warm: "Warm", cool: "Cool", bw: "Black & white", vintage: "Vintage", vivid: "Vivid",
                    faded: "Faded", cinematic: "Cinematic (teal & orange)", noir: "Noir",
                    horror: "Horror (sickly, dark edges)", vhs: "VHS tape", film: "Old film (grain)", vignette: "Vignette (dark edges)",
                    letterbox: "Cinema bars" }[l]}</option>)}
                </select>
              </label>
              <Slider label="Brightness" value={color.brightness} min={-0.5} max={0.5} step={0.01} fmt={signed} onChange={(v) => setColor({ brightness: v }, "Brightness")} />
              <Slider label="Contrast" value={color.contrast} min={0.3} max={2} step={0.01} fmt={pct} onChange={(v) => setColor({ contrast: v }, "Contrast")} />
              <Slider label="Saturation" value={color.saturation} min={0} max={2.5} step={0.01} fmt={pct} onChange={(v) => setColor({ saturation: v }, "Saturation")} />
              <Slider label="Gamma (midtones)" value={color.gamma} min={0.4} max={2.5} step={0.01} fmt={(v) => v.toFixed(2)} onChange={(v) => setColor({ gamma: v }, "Gamma")} />
              <Slider label="Temperature" value={color.temperature} min={-1} max={1} step={0.01} fmt={(v) => (v > 0 ? `warm ${signed(v)}` : v < 0 ? `cool ${signed(v)}` : "neutral")} onChange={(v) => setColor({ temperature: v }, "Temperature")} />
              <div className="dim" style={{ fontSize: 11 }}>The preview approximates colour; the export applies it exactly.</div>
            </div>
          </>
        )}
        {extra}
      </div>
    </div>
  );
}
