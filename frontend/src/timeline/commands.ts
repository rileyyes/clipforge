// Phase 21: edit by typing. A small, fixed set of plain-English commands, each turned into one
// of the editor's normal operations (so it's undoable and checked like a click). The optional
// local AI (backend /command/ai) only rewrites free-form requests into these same lines.
import { newEffectAt } from "./effects";
import { addMarker, addTitle, cutRanges, splitAt, TITLE_TEMPLATES, timelineDuration, updateMarker, updateTitle, type OpResult } from "./ops";
import { setBlend, setTrackMix } from "./phase20";
import { BLEND_MODES, type AudioSettings, type BlendMode, type Effect, type Sound, type Timeline, type TitleTemplate } from "./types";

export type Cmd =
  | { kind: "cut"; from: number; to: number }
  | { kind: "split"; at: number }
  | { kind: "effect"; effect: "zoom" | "shake" | "flash" | "bass"; at: number }
  | { kind: "sound"; sound: Sound; at: number }
  | { kind: "title"; template: TitleTemplate; label?: string; text?: string; at: number }
  | { kind: "marker"; at: number; label: string }
  | { kind: "volume"; target: string; value: number }
  | { kind: "mute" | "unmute" | "solo" | "unsolo"; target: string }
  | { kind: "go"; at: number }
  | { kind: "blend"; mode: BlendMode }
  | { kind: "undo" } | { kind: "redo" };

export interface Ctx { timeline: Timeline; effects: Effect[]; audio: AudioSettings; playhead: number; selection: string[] }
export interface Done {
  label: string; message: string;
  timeline?: Timeline; effects?: Effect[]; audio?: AudioSettings; seek?: number; undo?: boolean; redo?: boolean;
}

export const EXAMPLES = [
  "cut 0:10 to 0:20", "split at 1:05", "add a zoom at 1:05", "add a whoosh at 0:42", "add text \"NO WAY\" at 0:30",
  "add a title \"Chapter 2\" at 2:00", "add a bar chart", "add a progress bar", "add an end screen", "add a marker \"Intro\" at 0:00",
  "music to 30%", "sound effects to 50%", "mute A2", "solo A1", "go to 1:30", "blend screen", "undo",
];

const SOUNDS: Sound[] = ["beep", "boing", "scratch", "honk", "quack", "boom", "whoosh", "ding", "pop", "airhorn", "riser", "impact"];
const PRESETS: [RegExp, TitleTemplate, string?][] = [
  [/^(?:a )?(?:bar )?chart$/, "chart"], [/^(?:a )?(?:percent(?:age)? )?ring$/, "ring"], [/^(?:a )?(?:list|checklist|list reveal)$/, "list"],
  [/^(?:a )?progress bar$/, "progress"], [/^(?:a )?quote(?: card)?$/, "quote"], [/^(?:an? )?end ?screen$/, "end_screen"],
  [/^(?:a )?subscribe(?: button)?$/, "subscribe"], [/^(?:a )?timer$/, "ticker", "Timer"], [/^(?:a )?money ticker$/, "ticker", "Money ticker"],
  [/^(?:a )?lower third$/, "lower_third"], [/^(?:a )?chapter card$/, "chapter"], [/^(?:a )?highlighter$/, "highlight"],
  [/^(?:a )?(?:time (?:and|&) place|stamp)$/, "stamp"], [/^(?:a )?number card$/, "number_card"],
];

/** "1:05", "1:05.5", "0:01:05", "65", "65s", "65 seconds", "1m5s", "start", "end", "here". */
export function parseTime(s: string, ctx?: { playhead: number; end: number }): number | null {
  const t = s.trim().toLowerCase().replace(/^the /, "");
  if (["here", "now", "playhead", "the playhead"].includes(t)) return ctx ? ctx.playhead : null;
  if (["start", "beginning"].includes(t)) return 0;
  if (t === "end") return ctx ? ctx.end : null;
  let m = t.match(/^(\d+):(\d{1,2})(?::(\d{1,2}))?(?:\.(\d+))?$/);
  if (m) {
    const frac = m[4] ? +`0.${m[4]}` : 0;
    return m[3] !== undefined ? +m[1] * 3600 + +m[2] * 60 + +m[3] + frac : +m[1] * 60 + +m[2] + frac;
  }
  m = t.match(/^(?:(\d+)\s*m(?:in(?:utes?)?)?\s*)?(?:(\d+(?:\.\d+)?)\s*s(?:ec(?:onds?)?)?)?$/);
  if (m && (m[1] || m[2])) return (m[1] ? +m[1] * 60 : 0) + (m[2] ? +m[2] : 0);
  m = t.match(/^(\d+(?:\.\d+)?)$/);
  return m ? +m[1] : null;
}

const TIME = String.raw`((?:\d+:)?\d+(?::\d+)?(?:\.\d+)?|\d+(?:\.\d+)?\s*s(?:ec(?:onds?)?)?|\d+\s*m(?:in(?:utes?)?)?(?:\s*\d+(?:\.\d+)?\s*s(?:ec(?:onds?)?)?)?|(?:the )?(?:start|beginning|end|playhead)|here|now)`;
const AT = String.raw`(?:\s+(?:(?:at|@)\s+)?${TIME})?`;
const QUOTED = String.raw`["“']([^"”']{1,80})["”']`;

/** One line → a command (or why it wasn't understood). */
export function parseCommand(line: string, ctx: { playhead: number; end: number }): Cmd | { error: string } {
  const s = line.trim().replace(/[.!]+$/, "").replace(/\s+/g, " ");
  const low = s.toLowerCase();
  const time = (x: string | undefined) => (x === undefined ? ctx.playhead : parseTime(x, ctx));
  let m: RegExpMatchArray | null;
  if (/^(undo|undo that)$/.test(low)) return { kind: "undo" };
  if (/^redo$/.test(low)) return { kind: "redo" };
  if ((m = low.match(new RegExp(String.raw`^(?:cut|delete|remove|cut out)(?: out)?(?: from)? ${TIME} (?:to|-|–|until|till) ${TIME}$`)))) {
    const a = parseTime(m[1], ctx), b = parseTime(m[2], ctx);
    if (a === null || b === null) return { error: "I couldn't read those times." };
    if (b <= a) return { error: "The second time has to be after the first." };
    return { kind: "cut", from: a, to: b };
  }
  if ((m = low.match(new RegExp(String.raw`^(?:split|cut)(?: (?:it|the clips?))?${AT}$`)))) {
    const at = time(m[1]); return at === null ? { error: "I couldn't read that time." } : { kind: "split", at };
  }
  if ((m = low.match(new RegExp(String.raw`^(?:go|jump|skip|seek)(?: to)? ${TIME}$`)))) {
    const at = parseTime(m[1], ctx); return at === null ? { error: "I couldn't read that time." } : { kind: "go", at };
  }
  if ((m = low.match(new RegExp(String.raw`^add (?:an? |some )?(zoom|zoom in|punch in|punch-in|shake|screen shake|flash|bass boost)(?: effect)?${AT}$`)))) {
    const effect = m[1].startsWith("zoom") || m[1].startsWith("punch") ? "zoom" : m[1].includes("shake") ? "shake" : m[1] === "flash" ? "flash" : "bass";
    const at = time(m[2]); return at === null ? { error: "I couldn't read that time." } : { kind: "effect", effect, at };
  }
  if ((m = low.match(new RegExp(String.raw`^(?:add|play) (?:an? |the )?(${SOUNDS.join("|")})(?: sound(?: effect)?)?${AT}$`)))) {
    const at = time(m[2]); return at === null ? { error: "I couldn't read that time." } : { kind: "sound", sound: m[1] as Sound, at };
  }
  if ((m = s.match(new RegExp(String.raw`^add (?:an? )?(?:marker|chapter marker)(?: (?:called|named) )?(?: ?${QUOTED})?${AT}$`, "i")))) {
    const at = time(m[2]?.toLowerCase()); return at === null ? { error: "I couldn't read that time." } : { kind: "marker", at, label: m[1] ?? "" };
  }
  if ((m = s.match(new RegExp(String.raw`^add (?:an? )?(text|pop-?up text|words|title|big title|lower third|caption) ${QUOTED}${AT}$`, "i")))) {
    const what = m[1].toLowerCase();
    const template: TitleTemplate = what === "title" || what === "big title" ? "big_title" : what === "lower third" ? "lower_third" : "pop_text";
    const at = time(m[3]?.toLowerCase()); return at === null ? { error: "I couldn't read that time." } : { kind: "title", template, text: m[2], at };
  }
  if ((m = low.match(new RegExp(String.raw`^add (.+?)${AT}$`)))) {
    for (const [re, template, label] of PRESETS) if (re.test(m[1])) {
      const at = time(m[2]); return at === null ? { error: "I couldn't read that time." } : { kind: "title", template, label, at };
    }
  }
  if ((m = low.match(/^(?:set |turn )?(?:the )?(music|voice|voices|dialogue|narration|voice-?over|sound effects|effects|sfx|[av]\d+)(?: track)?(?: volume)? (?:to|at|down to|up to) (\d+(?:\.\d+)?)\s*%$/))) {
    const v = +m[2] / 100;
    if (v < 0 || v > 2) return { error: "Volumes go from 0% to 200%." };
    return { kind: "volume", target: m[1], value: v };
  }
  if ((m = low.match(/^(mute|unmute|solo|unsolo)(?: the)? (music|voice|voices|dialogue|narration|voice-?over|[av]\d+)(?: track)?$/)))
    return { kind: m[1] as "mute", target: m[2] };
  if ((m = low.match(/^(?:set )?blend(?: mode)?(?: to)? (normal|screen|multiply|overlay|lighten|darken|add|addition|difference|soft ?light)$/))) {
    const mode = (m[1] === "add" ? "addition" : m[1].replace(" ", "")) as BlendMode;
    return (BLEND_MODES as readonly string[]).includes(mode) ? { kind: "blend", mode } : { error: "Unknown blend mode." };
  }
  return { error: `I don't know "${s}" yet.` };
}

/** Audio tracks a target names: "music", "voice", "A2"… */
function tracksFor(tl: Timeline, target: string) {
  const t = target.toLowerCase();
  const audio = tl.tracks.filter((x) => x.kind === "audio");
  if (/^a\d+$/.test(t)) return audio.filter((x) => x.name.toLowerCase() === t);
  if (t === "music") return audio.filter((x) => x.role === "music");
  if (t.startsWith("narration") || t.startsWith("voice-") || t === "voiceover") return audio.filter((x) => x.role === "narration");
  return audio.filter((x) => (x.role ?? "dialogue") === "dialogue");
}

const fmt = (s: number) => `${Math.floor(s / 60)}:${(s % 60).toFixed(1).padStart(4, "0")}`;

export function runCommand(cmd: Cmd, ctx: Ctx): Done | { error: string } {
  const tl = ctx.timeline;
  const end = timelineDuration(tl);
  const ok = (r: OpResult, label: string, message: string): Done | { error: string } =>
    r.error || !r.timeline ? { error: r.error ?? "That didn't work." } : { timeline: r.timeline, label, message };
  switch (cmd.kind) {
    case "undo": return { undo: true, label: "Undo", message: "Undone" };
    case "redo": return { redo: true, label: "Redo", message: "Redone" };
    case "go": return { seek: Math.max(0, Math.min(end, cmd.at)), label: "Go", message: `Went to ${fmt(cmd.at)}` };
    case "cut": {
      if (cmd.from >= end) return { error: "That's after the end of the video." };
      return ok(cutRanges(tl, [[cmd.from, Math.min(end, cmd.to)]]), "Cut", `Cut ${fmt(cmd.from)}–${fmt(Math.min(end, cmd.to))} (everything after moved up)`);
    }
    case "split": {
      const ids = tl.tracks.filter((t) => !t.locked).flatMap((t) => t.clips.filter((c) => cmd.at > c.start && cmd.at < c.start + (c.source_out - c.source_in) / c.speed).map((c) => c.id));
      if (!ids.length) return { error: `Nothing to split at ${fmt(cmd.at)}.` };
      return ok(splitAt(tl, ids, cmd.at), "Split", `Split at ${fmt(cmd.at)}`);
    }
    case "effect": case "sound": {
      const e = cmd.kind === "sound" ? newEffectAt(tl, cmd.at, "sfx", { sound: cmd.sound }) : newEffectAt(tl, cmd.at, cmd.effect);
      if (!e) return { error: `There's no footage at ${fmt(cmd.at)} to put it on.` };
      const what = cmd.kind === "sound" ? `${cmd.sound} sound` : cmd.effect === "bass" ? "bass boost" : cmd.effect;
      return { effects: [...ctx.effects, e], label: `Add ${what}`, message: `Added a ${what} at ${fmt(cmd.at)}` };
    }
    case "title": {
      const r = addTitle(tl, cmd.template, Math.max(0, Math.min(end, cmd.at)), cmd.label);
      if (r.error || !r.timeline) return { error: r.error ?? "That didn't work." };
      let out = r.timeline;
      if (cmd.text !== undefined && r.id) out = updateTitle(out, r.id, { text: cmd.text.slice(0, 80) }).timeline ?? out;
      const name = TITLE_TEMPLATES.find((x) => x[0] === cmd.template && (!cmd.label || x[1] === cmd.label))?.[1] ?? "Title";
      return { timeline: out, label: `Add ${name.toLowerCase()}`, message: `Added ${name.toLowerCase()} — edit it in the Text tab` };
    }
    case "marker": {
      const r = addMarker(tl, Math.max(0, Math.min(end, cmd.at)));
      if (r.error || !r.timeline) return { error: r.error ?? "That didn't work." };
      const out = cmd.label && r.id ? updateMarker(r.timeline, r.id, { label: cmd.label.slice(0, 60) }).timeline ?? r.timeline : r.timeline;
      return { timeline: out, label: "Add marker", message: `Added a marker at ${fmt(cmd.at)}` };
    }
    case "volume": {
      if (/^(sound effects|effects|sfx)$/.test(cmd.target)) return { audio: { ...ctx.audio, fx_volume: cmd.value }, label: "Effects volume", message: `Sound effects at ${Math.round(cmd.value * 100)}%` };
      const ts = tracksFor(tl, cmd.target);
      if (!ts.length) return { error: `There's no ${cmd.target} track.` };
      let out = tl;
      for (const t of ts) out = setTrackMix(out, t.id, { volume: cmd.value }).timeline ?? out;
      return { timeline: out, label: "Track volume", message: `${ts.map((t) => t.name).join(", ")} at ${Math.round(cmd.value * 100)}%` };
    }
    case "mute": case "unmute": case "solo": case "unsolo": {
      const ts = tracksFor(tl, cmd.target);
      if (!ts.length) return { error: `There's no ${cmd.target} track.` };
      let out = tl;
      const patch = cmd.kind === "mute" ? { muted: true } : cmd.kind === "unmute" ? { muted: false } : cmd.kind === "solo" ? { solo: true } : { solo: false };
      for (const t of ts) out = setTrackMix(out, t.id, patch).timeline ?? out;
      return { timeline: out, label: `${cmd.kind[0].toUpperCase()}${cmd.kind.slice(1)} track`, message: `${cmd.kind[0].toUpperCase()}${cmd.kind.slice(1)}d ${ts.map((t) => t.name).join(", ")}` };
    }
    case "blend": {
      const vids = ctx.selection.filter((id) => tl.tracks.some((t) => t.kind === "video" && t.clips.some((c) => c.id === id)));
      if (!vids.length) return { error: "Select a clip on V2 or higher first." };
      return ok(setBlend(tl, vids, cmd.mode), "Blend mode", `Blend: ${cmd.mode}`);
    }
  }
}

/** Several lines (one command each, or separated by ";" / " then "). Stops at the first problem. */
export function splitLines(text: string): string[] {
  return text.split(/\n|;|\bthen\b|,\s*and then\b/i).map((x) => x.trim().replace(/^and /i, "")).filter(Boolean).slice(0, 20);
}
