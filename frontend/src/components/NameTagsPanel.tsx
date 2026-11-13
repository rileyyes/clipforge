import React from "react";
import { setTrackTag, type OpResult } from "../timeline/ops";
import type { NameTags, Timeline } from "../timeline/types";

/** Name tags over each speaker (Phase 18); the tag of whoever is talking lights up. */
export function NameTagsPanel({ timeline, commit }: { timeline: Timeline; commit: (r: OpResult, label: string, coalesce?: boolean) => boolean }) {
  const nt: NameTags = timeline.name_tags ?? { enabled: false, corner: "tl", size: 1, only_talking: false };
  const set = (p: Partial<NameTags>, label: string) => commit({ timeline: { ...timeline, name_tags: { ...nt, ...p } } }, label, true);
  const audio = timeline.tracks.filter((t) => t.kind === "audio" && t.role !== "music");
  return (
    <div className="insp-section" data-testid="name-tags">
      <h3 style={{ margin: 0 }}>Name tags</h3>
      <div className="dim" style={{ fontSize: 11 }}>Put each person's mic on its own audio track and give it a name: their tag lights up while their track is loud. It goes by loudness, so game sound on a mic counts as talking.</div>
      <label className="row" style={{ fontSize: 12 }}><input type="checkbox" checked={nt.enabled} aria-label="Show name tags" onChange={(e) => set({ enabled: e.target.checked }, "Name tags")} />Show name tags</label>
      {audio.map((t) => (
        <div key={t.id} className="row" style={{ gap: 6 }}>
          <span className="mono dim" style={{ width: 28 }}>{t.name}</span>
          <input type="text" value={t.tag ?? ""} maxLength={24} placeholder="Name" aria-label={`Name tag for ${t.name}`} style={{ flex: 1, minWidth: 0 }}
            onChange={(e) => commit(setTrackTag(timeline, t.id, e.target.value), "Name tag", true)} />
          <input type="color" style={{ flex: "none", width: 36 }} value={t.tag_color ?? "#5865f2"} aria-label={`Tag colour for ${t.name}`} onChange={(e) => commit(setTrackTag(timeline, t.id, t.tag ?? "", e.target.value), "Name tag colour", true)} />
        </div>
      ))}
      <div className="insp-grid">
        <label className="field">Corner<select value={nt.corner} aria-label="Name tag corner" onChange={(e) => set({ corner: e.target.value as NameTags["corner"] }, "Name tag corner")}>
          <option value="tl">Top left</option><option value="tr">Top right</option><option value="bl">Bottom left</option><option value="br">Bottom right</option></select></label>
        <label className="field">Size <span className="dim">{Math.round(nt.size * 100)}%</span>
          <input type="range" min={0.5} max={2} step={0.05} value={nt.size} onChange={(e) => set({ size: +e.target.value }, "Name tag size")} /></label>
      </div>
      <label className="row" style={{ fontSize: 12 }}><input type="checkbox" checked={nt.only_talking} onChange={(e) => set({ only_talking: e.target.checked }, "Name tags")} />Only show whoever is talking</label>
    </div>
  );
}
