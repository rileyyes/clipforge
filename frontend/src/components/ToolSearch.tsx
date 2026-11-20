import React, { useEffect, useRef, useState } from "react";
import { searchTools, type Tool } from "../timeline/tools";
import { Icon } from "./ui";

/** Ctrl+K (or the magnifier in the top bar): find any tool by name and jump to it. */
export default function ToolSearch({ onPick, onClose }: { onPick: (t: Tool) => void; onClose: () => void }) {
  const [q, setQ] = useState("");
  const [i, setI] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const list = searchTools(q);
  useEffect(() => { input.current?.focus(); }, []);
  useEffect(() => { setI(0); }, [q]);
  const pick = (t: Tool | undefined) => { if (t) { onClose(); onPick(t); } };
  return (
    <div className="modal-back tool-search-back" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="tool-search" role="dialog" aria-label="Find a tool" data-testid="tool-search">
        <div className="tool-search-input">
          <Icon name="search" size={16} />
          <input ref={input} type="text" aria-label="Find a tool" placeholder="Find a tool… (e.g. mixer, blur, chart, captions)" value={q} maxLength={80}
            role="combobox" aria-expanded aria-controls="tool-search-list" aria-activedescendant={list[i] ? `tool-${i}` : undefined}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => {
              e.stopPropagation();
              if (e.key === "ArrowDown") { e.preventDefault(); setI((x) => Math.min(list.length - 1, x + 1)); }
              else if (e.key === "ArrowUp") { e.preventDefault(); setI((x) => Math.max(0, x - 1)); }
              else if (e.key === "Enter") { e.preventDefault(); pick(list[i]); }
              else if (e.key === "Escape") { e.preventDefault(); onClose(); }
            }} />
          <kbd>Esc</kbd>
        </div>
        <div id="tool-search-list" role="listbox" className="tool-search-list">
          {!q.trim() && <div className="dim tool-search-hint">Popular</div>}
          {list.map((t, k) => (
            <div key={t.name} id={`tool-${k}`} role="option" aria-selected={k === i} className={"tool-search-item" + (k === i ? " on" : "")}
              onMouseEnter={() => setI(k)} onMouseDown={(e) => { e.preventDefault(); pick(t); }}>
              <span className="name">{t.name}</span>
              <span className="where">{t.where}{t.needsClip ? " (select a clip)" : ""}</span>
            </div>
          ))}
          {q.trim() && !list.length && <div className="dim tool-search-hint">Nothing called "{q}". Try another word, or type it in the AI tab's command box.</div>}
        </div>
      </div>
    </div>
  );
}
