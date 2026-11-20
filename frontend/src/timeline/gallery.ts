// Phase 22: how the Text tab's title gallery is grouped.
import { RETIRED_TEMPLATES, TITLE_TEMPLATES } from "./ops";
import type { Title, TitleTemplate } from "./types";

export const GROUPS: [string, TitleTemplate[]][] = [
  ["Titles", ["lower_third", "big_title", "top_banner", "chapter", "pop_text", "stamp"]],
  ["Arrows & shapes", ["arrow", "circle", "box", "highlight", "route", "number_card", "sticker"]],
  ["Motion graphics", ["chart", "ring", "list", "ticker", "progress", "quote"]],
  ["YouTube", ["subscribe", "end_screen"]],
];

type Entry = [TitleTemplate, string, Partial<Title>];

/** Every template offered, in its group (anything not listed goes under "More"). */
export function grouped(): [string, Entry[]][] {
  const offered = TITLE_TEMPLATES.filter(([tpl]) => !RETIRED_TEMPLATES.includes(tpl)) as Entry[];
  const used = new Set<Entry>();
  const out: [string, Entry[]][] = GROUPS.map(([g, tpls]) => {
    const items = offered.filter((e) => tpls.includes(e[0]));
    items.forEach((e) => used.add(e));
    return [g, items];
  });
  const rest = offered.filter((e) => !used.has(e));
  if (rest.length) out.push(["More", rest]);
  return out.filter(([, items]) => items.length > 0);
}

