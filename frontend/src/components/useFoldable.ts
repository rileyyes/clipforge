import { useEffect, useLayoutEffect, useState, type RefObject } from "react";

// Phase 22: every section of the tool panel can be folded away by clicking its heading
// (or Enter / Space on it). Which ones are folded is kept in this browser. Works on any
// `.insp-section` whose first child is an <h3> (or a row starting with one), so panels
// don't need to change.

const KEY = "cf:folded";

function load(): Set<string> {
  try { const v = JSON.parse(localStorage.getItem(KEY) ?? "[]"); return new Set(Array.isArray(v) ? v.filter((x) => typeof x === "string").slice(0, 300) : []); }
  catch { return new Set(); }
}
function store(s: Set<string>) {
  try { localStorage.setItem(KEY, JSON.stringify([...s])); } catch { /* storage unavailable */ }
}

/** The heading that folds a section, if it has one. */
export function headingOf(sec: Element): HTMLElement | null {
  const first = sec.firstElementChild;
  if (!first) return null;
  if (first.tagName === "H3") return first as HTMLElement;
  if (first.classList.contains("row") && first.firstElementChild?.tagName === "H3") return first.firstElementChild as HTMLElement;
  return null;
}
export const sectionKey = (tab: string, h: HTMLElement) => `${tab}:${(h.textContent ?? "").trim().toLowerCase().slice(0, 60)}`;

export function useFoldable(ref: RefObject<HTMLElement | null>, tab: string) {
  const [folded, setFolded] = useState<Set<string>>(load);

  // mark the sections after every render (React leaves these attributes alone)
  useLayoutEffect(() => {
    const root = ref.current;
    if (!root) return;
    root.querySelectorAll(".insp-section").forEach((sec) => {
      const h = headingOf(sec);
      if (!h) return;
      const key = sectionKey(tab, h);
      const isFolded = folded.has(key);
      sec.setAttribute("data-foldable", "");
      if (isFolded) sec.setAttribute("data-folded", ""); else sec.removeAttribute("data-folded");
      h.setAttribute("role", "button");
      h.setAttribute("tabindex", "0");
      h.setAttribute("aria-expanded", String(!isFolded));
      h.setAttribute("title", isFolded ? "Show this section" : "Fold this section away");
    });
  });

  useEffect(() => {
    const root = ref.current;
    if (!root) return;
    const toggle = (h: HTMLElement) => {
      const key = sectionKey(tab, h);
      setFolded((cur) => {
        const next = new Set(cur);
        if (next.has(key)) next.delete(key); else next.add(key);
        store(next);
        return next;
      });
    };
    const target = (e: Event) => {
      const h = (e.target as HTMLElement | null)?.closest?.("h3[role=button]") as HTMLElement | null;
      return h && h.closest(".insp-section[data-foldable]") && root.contains(h) ? h : null;
    };
    const onClick = (e: MouseEvent) => { const h = target(e); if (h) toggle(h); };
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Enter" && e.key !== " ") return;
      const h = target(e);
      if (h) { e.preventDefault(); e.stopPropagation(); toggle(h); }
    };
    root.addEventListener("click", onClick);
    root.addEventListener("keydown", onKey);
    return () => { root.removeEventListener("click", onClick); root.removeEventListener("keydown", onKey); };
  }, [tab]);

  /** Unfold a section (the tool search jumps to it). */
  const unfold = (key: string) => setFolded((cur) => {
    if (!cur.has(key)) return cur;
    const next = new Set(cur); next.delete(key); store(next); return next;
  });
  const setAll = (keys: string[], fold: boolean) => setFolded((cur) => {
    const next = new Set(cur);
    for (const k of keys) { if (fold) next.add(k); else next.delete(k); }
    store(next); return next;
  });
  return { folded, unfold, setAll };
}
