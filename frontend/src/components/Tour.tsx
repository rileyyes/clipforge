import React, { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

/** First-run tour of the editor: a few steps, each pointing at one part of the screen.
 *  Shown once (remembered in this browser); Settings → "Show the tour again" brings it back.
 *  It doesn't start by itself in automated browsers (navigator.webdriver), so the automated
 *  tests that open the editor aren't blocked by it; the Phase 17 test starts it from Settings. */

const KEY = "rj:tour";  // absent = never seen, "done" = finished or skipped, "again" = show on next editor visit

export function tourWanted(): boolean {
  try {
    const v = localStorage.getItem(KEY);
    if (v === "again") return true;
    return v === null && !navigator.webdriver;
  } catch { return false; }
}
export function tourAgain() { try { localStorage.setItem(KEY, "again"); } catch { /* storage unavailable */ } }
function tourDone() { try { localStorage.setItem(KEY, "done"); } catch { /* storage unavailable */ } }

type Step = { target?: string; title: string; text: string };
export const TOUR_STEPS: Step[] = [
  { title: "Welcome to RJClip", text: "A 30-second look around the editor. Everything runs on your computer — nothing is uploaded unless you choose Publish. Tip: the AI Auto Editor (the wand on the left) can make a first cut for you." },
  { target: ".ed-mid > .pane:first-of-type", title: "Your media", text: "Import recordings, music and images here (or drag files in). Click one to add it to the end of the timeline, or drag it where you want it." },
  { target: ".monitor", title: "Preview", text: "Plays your edit with titles, effects, captions and music. Space plays and pauses; click a title here to drag it into place." },
  { target: ".timeline", title: "Timeline", text: "Drag clips to move them, drag their edges to trim, S splits at the playhead, Ctrl+Z undoes. Titles, blurs and markers move with the clip they sit on." },
  { target: ".side-tabs", title: "Tools", text: "Clip settings and looks, effects and captions, text (fonts, stickers, counter, name tags), edit by script, privacy blur, music, face cam, AI help (funny moments, hook checker, B-roll, voiceover) and saved versions." },
  { target: "[data-tour=export]", title: "Export", text: "When you're happy, Export makes the MP4. Your edits save automatically as you go." },
  { title: "That's it", text: "Press ? any time for the keyboard shortcuts. You can see this tour again from Settings." },
];

type Box = { x: number; y: number; w: number; h: number };
const PAD = 6, CARD_W = 340, GAP = 12;

export default function Tour({ onClose }: { onClose: () => void }) {
  const [i, setI] = useState(0);
  const [box, setBox] = useState<Box | null>(null);
  const [cardH, setCardH] = useState(180);
  const [view, setView] = useState({ w: window.innerWidth, h: window.innerHeight });
  const cardRef = useRef<HTMLDivElement>(null);
  const nextRef = useRef<HTMLButtonElement>(null);
  const step = TOUR_STEPS[i];
  const last = i === TOUR_STEPS.length - 1;

  const finish = useCallback(() => { tourDone(); onClose(); }, [onClose]);
  const measure = useCallback(() => {
    setView({ w: window.innerWidth, h: window.innerHeight });
    const el = step.target ? document.querySelector(step.target) : null;
    const r = el?.getBoundingClientRect();
    if (!r || r.width <= 0 || r.height <= 0) { setBox(null); return; }
    // padded, but kept on screen (the ring would be cut off at the edges otherwise)
    const x0 = Math.max(2, r.left - PAD), y0 = Math.max(2, r.top - PAD);
    const x1 = Math.min(window.innerWidth - 2, r.right + PAD), y1 = Math.min(window.innerHeight - 2, r.bottom + PAD);
    setBox({ x: x0, y: y0, w: x1 - x0, h: y1 - y0 });
  }, [step]);

  useLayoutEffect(() => { measure(); }, [measure]);
  useLayoutEffect(() => { if (cardRef.current) setCardH(cardRef.current.offsetHeight); });
  useEffect(() => {
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, [measure]);
  useEffect(() => { nextRef.current?.focus(); }, [i]);
  useEffect(() => {
    // capture phase: the editor's own shortcuts (Space, S, Delete…) must not fire behind the tour
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Tab") return;
      e.stopPropagation();
      if (e.key === "Escape") { e.preventDefault(); finish(); }
      else if (e.key === "ArrowRight") { e.preventDefault(); if (last) finish(); else setI((n) => n + 1); }
      else if (e.key === "ArrowLeft") { e.preventDefault(); setI((n) => Math.max(0, n - 1)); }
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [finish, last]);

  // card: below the highlighted area if it fits, else above, else beside it, else centred
  let left = (view.w - CARD_W) / 2, top = (view.h - cardH) / 2;
  if (box) {
    const clampX = (x: number) => Math.max(GAP, Math.min(view.w - CARD_W - GAP, x));
    const clampY = (y: number) => Math.max(GAP, Math.min(view.h - cardH - GAP, y));
    if (box.y + box.h + GAP + cardH <= view.h) { top = box.y + box.h + GAP; left = clampX(box.x); }
    else if (box.y - GAP - cardH >= 0) { top = box.y - GAP - cardH; left = clampX(box.x); }
    else if (box.x - GAP - CARD_W >= 0) { left = box.x - GAP - CARD_W; top = clampY(box.y); }
    else if (box.x + box.w + GAP + CARD_W <= view.w) { left = box.x + box.w + GAP; top = clampY(box.y); }
  }

  return (
    <div className="tour" data-testid="tour">
      <div className="tour-block" />
      {box ? <div className="tour-hole" style={{ left: box.x, top: box.y, width: box.w, height: box.h }} />
        : <div className="tour-dim" />}
      <div ref={cardRef} className="tour-card" role="dialog" aria-modal="true" aria-labelledby="tour-title"
        style={{ left, top, width: CARD_W }}>
        <div className="tour-count">{i + 1} / {TOUR_STEPS.length}</div>
        <h3 id="tour-title">{step.title}</h3>
        <p>{step.text}</p>
        <div className="row" style={{ gap: 8 }}>
          {!last && <button className="btn ghost sm" onClick={finish}>Skip tour</button>}
          <span className="spacer" />
          {i > 0 && <button className="btn sm" onClick={() => setI(i - 1)}>Back</button>}
          <button ref={nextRef} className="btn primary sm" onClick={() => (last ? finish() : setI(i + 1))}>{last ? "Start editing" : "Next"}</button>
        </div>
      </div>
    </div>
  );
}
