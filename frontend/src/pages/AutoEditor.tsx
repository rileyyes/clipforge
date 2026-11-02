import React from "react";
import { Icon } from "../components/ui";

// Honest status page: the automatic editing engine is not built yet, so this page
// contains no controls that pretend to work.
const PLAN = [
  ["Transcription", "Local speech-to-text with word timestamps (faster-whisper, no paid API)."],
  ["Silence & pacing", "Conservative / balanced / aggressive dead-air removal that keeps natural pauses."],
  ["Scene & shot detection", "Frame-difference analysis on a low-res proxy, chunked for 2-hour recordings."],
  ["Highlight scoring", "Explainable scores from speech, audio energy, laughter and scene signals with your weights."],
  ["Duration planner", "Picks a coherent set of segments for your target length and warns when it's unrealistic."],
  ["Review & approve", "Every cut shown with its reason; accept, reject or tweak before rendering."],
  ["Send to Manual Editor", "The rough cut opens as normal clips on the timeline — same project, fully editable."],
];

export default function AutoEditor() {
  return (
    <div className="page" style={{ maxWidth: 860 }}>
      <h1>AI Auto Editor</h1>
      <p className="muted">Not built yet — this is Phase 3 of the roadmap. The manual editor and export pipeline it builds on are working now.</p>
      <div className="card" style={{ marginTop: 18 }}>
        <h3>What this section will do</h3>
        <div className="grid" style={{ gap: 12 }}>
          {PLAN.map(([t, d], i) => (
            <div key={t} className="row" style={{ alignItems: "start", gap: 12 }}>
              <span className="chip" style={{ minWidth: 22, justifyContent: "center" }}>{i + 1}</span>
              <div><strong>{t}</strong><div className="muted" style={{ fontSize: 12 }}>{d}</div></div>
            </div>
          ))}
        </div>
      </div>
      <div className="row" style={{ marginTop: 18 }}>
        <a className="btn primary" href="#/editor" style={{ textDecoration: "none" }}><Icon name="film" />Open Manual Editor</a>
      </div>
    </div>
  );
}
