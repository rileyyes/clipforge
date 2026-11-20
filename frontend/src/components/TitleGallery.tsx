import React, { memo, useCallback, useLayoutEffect, useRef } from "react";
import { grouped } from "../timeline/gallery";
import type { Title, TitleTemplate } from "../timeline/types";
import TitlesPreview from "./TitlesPreview";

// Phase 22: Text tab → add a title: a gallery of small live previews, in groups.

const W = 1920, H = 1080, CARD_W = 104;

/** A sample of the template, shown part-way through its animation. */
export function sample(tpl: TitleTemplate, label: string, preset: Partial<Title>): { title: Title; at: number } {
  const duration = tpl === "progress" ? 10 : preset.duration ?? 4;
  const title: Title = { id: `sample-${tpl}-${label}`, start: 0, duration, template: tpl, color: "#ffffff", accent: "#ff5a3c", align: "left", size: 1,
    subtext: "", ...preset, text: preset.text || (["arrow", "circle", "box", "highlight", "route", "sticker"].includes(tpl) ? preset.text ?? "" : label) } as Title;
  if (preset.items) title.items = preset.items.map((it) => ({ ...it }));
  const at = tpl === "progress" ? 5 : tpl === "list" ? Math.min(duration - 0.5, 2.2) : Math.min(duration * 0.6, 1.6);
  return { title, at };
}

function Card({ tpl, label, preset, onAdd }: { tpl: TitleTemplate; label: string; preset: Partial<Title>; onAdd: (tpl: TitleTemplate, label: string) => void }) {
  const { title, at } = sample(tpl, label, preset);
  const k = CARD_W / W;
  return (
    <button className="tg-card" aria-label={label} title={`Add ${label.toLowerCase()} at the playhead`} onClick={() => onAdd(tpl, label)}>
      <div className="tg-thumb" aria-hidden>
        <TitlesPreview titles={[title]} t={at} k={k} W={W} H={H} ox={0} oy={0} markers={tpl === "progress" ? [
          { id: "m1", t: 0, label: "Intro", color: "#ffb703" }, { id: "m2", t: 4, label: "Part 2", color: "#ffb703" }] as any : []} />
      </div>
      <span className="tg-label">{label}</span>
    </button>
  );
}

/** The samples are rendered once (they never change); test ids inside them are removed so
 *  they're never mistaken for titles on the preview. */
const Cards = memo(function Cards({ onAdd }: { onAdd: (tpl: TitleTemplate, label: string) => void }) {
  const root = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    root.current?.querySelectorAll("[data-testid], [data-template]").forEach((e) => {
      if (e.closest(".tg-thumb")) { e.removeAttribute("data-testid"); e.removeAttribute("data-template"); }
    });
  });
  return (
    <div ref={root} className="title-gallery" data-testid="title-gallery">
      {grouped().map(([g, items]) => (
        <div key={g} className="tg-group">
          <div className="tg-head">{g}</div>
          <div className="tg-grid">
            {items.map(([tpl, label, preset]) => <Card key={tpl + label} tpl={tpl} label={label} preset={preset} onAdd={onAdd} />)}
          </div>
        </div>
      ))}
    </div>
  );
});

/** Always calls the latest onAdd (so a title goes in at the current playhead, on the current edit). */
export default function TitleGallery({ onAdd }: { onAdd: (tpl: TitleTemplate, label: string) => void }) {
  const latest = useRef(onAdd);
  latest.current = onAdd;
  const stable = useCallback((tpl: TitleTemplate, label: string) => latest.current(tpl, label), []);
  return <Cards onAdd={stable} />;
}
