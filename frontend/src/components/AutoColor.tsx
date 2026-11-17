import React, { useState } from "react";
import { call } from "../api";
import { applyAutoColor } from "../timeline/phase21";
import type { OpResult } from "../timeline/ops";
import type { ColorAdjust, MediaMap, Timeline } from "../timeline/types";
import { useToast } from "./ui";

interface Result { color: ColorAdjust; changed: boolean }

/** Clip → Colour → Auto (Phase 21): fix exposure and white balance of this recording, or make
 *  it match another camera. Applies to every clip of the recording; one Ctrl+Z undoes it. */
export default function AutoColor({ projectId, timeline, media, mediaId, commit, saved }: {
  projectId: string; timeline: Timeline; media: MediaMap; mediaId: string;
  commit: (r: OpResult, label: string) => boolean; saved: boolean;
}) {
  const toast = useToast();
  const [busy, setBusy] = useState("");
  const others = [...new Set(timeline.tracks.filter((t) => t.kind === "video").flatMap((t) => t.clips.map((c) => c.media_id)))]
    .filter((id) => id !== mediaId && media[id]?.has_video && media[id]?.kind === "video");
  const [ref, setRef] = useState("");
  const run = async (mode: "fix" | "match") => {
    setBusy(mode);
    try {
      const r = await call<{ results: Record<string, Result> }>("POST", `/api/projects/${projectId}/color/auto`,
        { media_ids: [mediaId], mode, reference_media_id: mode === "match" ? ref : null });
      const got = r.results[mediaId];
      if (!got) { toast("Couldn't read frames from this recording.", true); return; }
      if (!got.changed) { toast(mode === "fix" ? "It already looks right: nothing to fix." : "It already matches."); return; }
      if (commit(applyAutoColor(timeline, { [mediaId]: got.color }), mode === "fix" ? "Auto colour" : "Match colour"))
        toast(mode === "fix" ? "Colour fixed on every clip of this recording (Ctrl+Z undoes it)" : `Matched to ${media[ref]?.original_name}`);
    } catch (e: any) { toast(e.message, true); }
    finally { setBusy(""); }
  };
  return (
    <div style={{ display: "grid", gap: 4 }} data-testid="auto-color">
      <div className="row" style={{ gap: 4, flexWrap: "wrap" }}>
        <button className="btn xs" disabled={!!busy || !saved} onClick={() => run("fix")}
          title="Fixes exposure (too dark / too bright / flat) and white balance (too blue / too orange) for every clip of this recording">
          {busy === "fix" ? "Fixing…" : "Auto fix"}</button>
        {others.length > 0 && <>
          <select aria-label="Camera to match" value={ref} style={{ flex: 1, minWidth: 0 }} onChange={(e) => setRef(e.target.value)}>
            <option value="">Match another camera…</option>
            {others.map((id) => <option key={id} value={id}>{media[id]?.original_name}</option>)}
          </select>
          <button className="btn xs" disabled={!!busy || !ref || !saved} onClick={() => run("match")}>{busy === "match" ? "Matching…" : "Match"}</button>
        </>}
      </div>
      <div className="dim" style={{ fontSize: 11 }}>Measures frames from across the recording and sets the sliders below. Your look stays.</div>
    </div>
  );
}
