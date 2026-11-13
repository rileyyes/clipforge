import React from "react";
import { fontCss, useFonts } from "../fonts";

/** A font picker grouped by style (Bold, Horror, Fun…, Yours). Each name is shown in its own font. */
export default function FontSelect({ value, onChange, label = "Font", stickers = false }: {
  value: string | null | undefined; onChange: (id: string | null) => void; label?: string;
  /** include the sticker (emoji) font */
  stickers?: boolean;
}) {
  const fonts = useFonts().filter((f) => stickers || f.category !== "Stickers");
  const groups = [...new Set(fonts.map((f) => f.category))];
  return (
    <label className="field">{label}
      <select aria-label={label} value={value ?? ""} onChange={(e) => onChange(e.target.value || null)}
        style={{ fontFamily: fontCss(value), fontSize: 14 }}>
        <option value="" style={{ fontFamily: fontCss(null) }}>Default</option>
        {groups.map((g) => (
          <optgroup key={g} label={g}>
            {fonts.filter((f) => f.category === g).map((f) => (
              <option key={f.id} value={f.id} style={{ fontFamily: fontCss(f.id) }}>{f.name ?? f.family}</option>
            ))}
          </optgroup>
        ))}
        {value && !fonts.some((f) => f.id === value) && <option value={value}>(font removed — default is used)</option>}
      </select>
    </label>
  );
}
