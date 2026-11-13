import React, { useEffect, useState } from "react";
import { fontCss, fontsApi } from "../fonts";
import { counterTicks, counterValue, taggedTracks, trackTalk } from "../timeline/phase18";
import type { Effect, Timeline } from "../timeline/types";

/** Counters and name tags on the preview (export: backend/app/overlays.py, same sizes/places). */
export default function OverlaysPreview({ projectId, timeline, effects, t, k, W, H, oy }: {
  projectId: string; timeline: Timeline; effects: Effect[]; t: number; k: number; W: number; H: number; oy: number;
}) {
  const talk = useTalk(projectId, timeline);
  const counters = timeline.counters ?? [];
  const nt = timeline.name_tags;
  const tagged = nt?.enabled ? taggedTracks(timeline) : [];
  const D = Math.max(0, ...timeline.tracks.flatMap((tr) => tr.clips.map((c) => c.start + (c.source_out - c.source_in) / c.speed)));
  return <>
    {counters.map((c) => {
      const end = c.end ?? D;
      if (t < c.start || t >= end) return null;
      const ticks = counterTicks(timeline, effects, c.id).filter((x) => x < end);
      const v = counterValue(c, ticks, t);
      const last = [...ticks].reverse().find((x) => x <= t + 1e-6);
      const since = last === undefined ? Infinity : t - last;
      const pop = since < 0.25 ? 1.6 - 0.6 * (since / 0.25) : 1;
      const flash = since < 0.5;
      const s = (H / 1080) * c.size * k;
      return (
        <div key={c.id} data-testid="counter-preview" data-value={v} style={{ position: "absolute", left: c.x * W * k, top: oy + c.y * H * k,
          transform: "translate(-50%,-50%)", background: "rgba(0,0,0,.72)", border: `${Math.max(1.5, 4 * s / k) * k}px solid ${c.accent}`,
          borderRadius: 12 * s, padding: `${18 * s * 0.8}px ${18 * s}px ${18 * s * 0.5}px`, textAlign: "center", pointerEvents: "none",
          zIndex: 1700, fontFamily: fontCss(c.font), fontWeight: c.font ? 400 : 700, color: c.color, minWidth: 70 * s }}>
          {c.label && <div style={{ fontSize: 30 * s, lineHeight: 1.2, opacity: 0.88 }}>{c.label.toUpperCase()}</div>}
          <div style={{ fontSize: 86 * s, lineHeight: 1.05, color: flash ? c.accent : c.color, transform: `scale(${pop})`,
            WebkitTextStroke: `${3 * s * 2}px #000`, paintOrder: "stroke fill" }}>{v}</div>
        </div>
      );
    })}
    {tagged.length > 0 && (() => {
      const s = (H / 1080) * (nt!.size ?? 1) * k;
      const right = nt!.corner.endsWith("r"), bottom = nt!.corner.startsWith("b");
      return (
        <div data-testid="name-tags-preview" style={{ position: "absolute", pointerEvents: "none", zIndex: 1700, display: "flex",
          flexDirection: bottom ? "column-reverse" : "column", gap: 8 * s, alignItems: "stretch",  /* every row as wide as the widest name, like the export */
          [right ? "right" : "left"]: W * k * 0.025, [bottom ? "bottom" : "top"]: (bottom ? oy : oy) + H * k * 0.04 } as React.CSSProperties}>
          {(bottom ? [...tagged].reverse() : tagged).map((tr) => {
            const on = trackTalk(tr, talk).some(([a, b]) => t >= a && t < b);
            if (nt!.only_talking && !on) return <div key={tr.id} style={{ height: 34 * s * 1.55 }} />;
            return (
              <div key={tr.id} data-testid="name-tag" data-talking={on ? "1" : "0"} style={{ display: "flex", alignItems: "center", gap: 14 * s,
                height: 34 * s * 1.55, padding: `0 ${14 * s}px`, borderRadius: 34 * s, minWidth: 0,
                background: on ? tr.tag_color ?? "#5865f2" : "rgba(0,0,0,.56)", boxShadow: on ? `${2 * s}px ${2 * s}px 0 rgba(0,0,0,.4)` : undefined }}>
                <span style={{ width: 18 * s, height: 18 * s, borderRadius: "50%", background: on ? "#3ba55d" : "#80848e",
                  boxShadow: on ? `0 0 0 ${2 * s}px #fff` : undefined, flex: "none" }} />
                <span style={{ fontSize: 34 * s, fontWeight: 700, color: "#fff", opacity: on ? 1 : 0.7, fontFamily: fontCss(null), whiteSpace: "nowrap" }}>{tr.tag}</span>
              </div>
            );
          })}
        </div>
      );
    })()}
  </>;
}

/** Talking stretches (source seconds) of each recording on a tagged track, fetched once per recording. */
const talkCache = new Map<string, [number, number][]>();
function useTalk(projectId: string, timeline: Timeline): Record<string, [number, number][]> {
  const [, bump] = useState(0);
  const ids = timeline.name_tags?.enabled ? [...new Set(taggedTracks(timeline).flatMap((t) => t.clips.map((c) => c.media_id)))] : [];
  const key = ids.sort().join(",");
  useEffect(() => {
    let live = true;
    for (const id of ids) {
      const k = `${projectId}:${id}`;
      if (talkCache.has(k)) continue;
      talkCache.set(k, []);
      fontsApi.talk(projectId, id).then((iv) => { talkCache.set(k, iv); if (live) bump((n) => n + 1); })
        .catch(() => talkCache.delete(k));
    }
    return () => { live = false; };
  }, [projectId, key]);
  return Object.fromEntries(ids.map((id) => [id, talkCache.get(`${projectId}:${id}`) ?? []]));
}
