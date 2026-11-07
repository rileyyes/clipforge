import React, { useEffect, useState } from "react";
import { brandApi, type BrandPayload } from "./BrandKit";
import { placeBrandClip } from "../timeline/pro";
import type { OpResult } from "../timeline/ops";
import type { CaptionSettings, MediaAsset, Timeline } from "../timeline/types";
import { Icon, useToast } from "./ui";

/** Editor → Text: apply the brand kit (Settings → Brand kit) to this video. */
export default function BrandApply({ projectId, timeline, captions, watermarkOn, commit, setCaptions, onWatermark, onMediaAdded }: {
  projectId: string; timeline: Timeline; captions: CaptionSettings; watermarkOn: boolean;
  commit: (r: OpResult, label: string) => boolean;
  setCaptions: (c: CaptionSettings, label: string) => void;
  onWatermark: (on: boolean) => void;
  onMediaAdded: () => Promise<void> | void;
}) {
  const toast = useToast();
  const [kit, setKit] = useState<BrandPayload | null>(null);
  const [pick, setPick] = useState({ logo: true, intro: true, outro: true, colours: true, captions: true });
  const [busy, setBusy] = useState(false);
  useEffect(() => { brandApi.get().then((k) => { setKit(k); setPick({ logo: k.has_logo, intro: k.has_intro, outro: k.has_outro, colours: true, captions: true }); }).catch(() => {}); }, []);
  if (!kit) return null;
  const post = async (path: string, body: object) => {
    const r = await fetch(`/api/projects/${projectId}${path}`, { method: "POST", headers: { "X-RJClip": "1", "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const d = await r.json(); if (!r.ok) throw new Error(d.error); return d;
  };
  const apply = async () => {
    setBusy(true);
    const done: string[] = [];
    try {
      if (pick.logo && kit.has_logo) { await post("/brand/watermark", { on: true }); onWatermark(true); done.push("logo"); }
      let tl = timeline;
      for (const where of ["intro", "outro"] as const) {
        if (!pick[where] || !(where === "intro" ? kit.has_intro : kit.has_outro)) continue;
        const r = await post("/brand/import", { kind: where });
        await onMediaAdded();
        const placed = placeBrandClip(tl, r.media as MediaAsset, where === "intro" ? "start" : "end");
        if (placed.error) throw new Error(placed.error);
        tl = placed.timeline!;
        done.push(where);
      }
      if (pick.colours && (tl.titles ?? []).length) {
        tl = { ...tl, titles: tl.titles!.map((t) => ({ ...t, color: kit.brand.title_color, accent: kit.brand.title_accent })) };
        done.push("title colours");
      }
      if (tl !== timeline) commit({ timeline: tl }, "Apply brand kit");
      if (pick.captions) { setCaptions({ ...captions, ...kit.brand.captions }, "Apply brand kit"); done.push("caption style"); }
      toast(done.length ? `Brand kit applied: ${done.join(", ")}` : "Nothing to apply — set up your kit in Settings first", !done.length);
    } catch (e: any) { toast(`Couldn't apply the brand kit: ${e.message}`, true); }
    finally { setBusy(false); }
  };
  const box = (k: keyof typeof pick, label: string, ok = true) => (
    <label className="row" style={{ gap: 4, fontSize: 12, opacity: ok ? 1 : 0.5 }}>
      <input type="checkbox" disabled={!ok} checked={ok && pick[k]} onChange={(e) => setPick({ ...pick, [k]: e.target.checked })} />{label}</label>
  );
  return (
    <div className="insp-section" style={{ marginBottom: 0, display: "grid", gap: 6 }} data-testid="brand-apply">
      <div className="row"><h3 style={{ margin: 0 }}>Brand kit{kit.brand.name ? `: ${kit.brand.name}` : ""}</h3><span className="spacer" />
        <a href="#/settings" className="dim" style={{ fontSize: 11 }}>Set up</a></div>
      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) minmax(0,1fr)", gap: 2 }}>
        {box("logo", "Logo watermark", kit.has_logo)}{box("captions", "Caption style")}
        {box("intro", "Intro at the start", kit.has_intro)}{box("colours", "Title colours")}
        {box("outro", "Outro at the end", kit.has_outro)}
      </div>
      <div className="row" style={{ gap: 6 }}>
        <button className="btn sm primary" disabled={busy} onClick={apply}><Icon name="wand" size={13} />{busy ? "Applying…" : "Apply my brand kit"}</button>
        {watermarkOn && <button className="btn sm ghost" onClick={async () => { await post("/brand/watermark", { on: false }); onWatermark(false); toast("Logo removed from this video"); }}>Remove logo</button>}
      </div>
    </div>
  );
}
