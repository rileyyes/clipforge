import React, { useRef, useState } from "react";
import { fontCss, fontsApi, setFonts, useFonts } from "../fonts";
import { Icon, useToast } from "./ui";

/** Settings → Fonts: the built-in fonts, and adding/removing your own .ttf/.otf files. */
export default function FontsCard() {
  const fonts = useFonts();
  const toast = useToast();
  const ref = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const mine = fonts.filter((f) => f.source === "yours");
  const built = fonts.filter((f) => f.source === "builtin" && f.category !== "Stickers");
  return (
    <div className="card" data-testid="fonts-card">
      <h3>Fonts</h3>
      <p className="muted" style={{ fontSize: 12, marginTop: 0 }}>
        {built.length} free fonts come with RJClip (and emoji stickers). Add your own .ttf or .otf files to use them in titles, captions and counters.
        Only add fonts you're allowed to use in videos — free fonts from Google Fonts are fine.
      </p>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginBottom: 10 }}>
        {built.map((f) => <span key={f.id} title={f.category} style={{ fontFamily: fontCss(f.id), fontSize: 18 }}>{f.family}</span>)}
      </div>
      {mine.map((f) => (
        <div key={f.id} className="row" style={{ gap: 8 }} data-testid="my-font">
          <span style={{ fontFamily: fontCss(f.id), fontSize: 20 }} className="grow ellipsis">{f.name ?? f.family}</span>
          <span className="dim" style={{ fontSize: 11 }}>{f.family}</span>
          <button className="btn xs ghost" aria-label={`Remove font ${f.family}`} onClick={async () => {
            if (!confirm(`Remove “${f.family}”? Titles that use it go back to the default font.`)) return;
            try { setFonts(await fontsApi.remove(f.id)); } catch (e: any) { toast(e.message, true); }
          }}><Icon name="trash" size={12} /></button>
        </div>
      ))}
      <button className="btn" disabled={busy} onClick={() => ref.current?.click()}><Icon name="plus" size={14} />{busy ? "Adding…" : "Add a font file"}</button>
      <input ref={ref} type="file" hidden accept=".ttf,.otf,font/ttf,font/otf" aria-label="Font file" onChange={async (e) => {
        const f = e.target.files?.[0]; e.target.value = "";
        if (!f) return;
        setBusy(true);
        try { setFonts(await fontsApi.add(f)); toast(`Added ${f.name}`); } catch (err: any) { toast(err.message, true); } finally { setBusy(false); }
      }} />
    </div>
  );
}
