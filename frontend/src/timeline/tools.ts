// Phase 22: the tool search (Ctrl+K). Every tool, where it lives (tab + section heading) and
// the words people might type for it.

export type Tab = "clip" | "fx" | "text" | "blur" | "beat" | "script" | "cam" | "ai" | "history";
export type Action = "export" | "marker" | "fit" | "shortcuts" | "reset-panels" | "toggle-media" | "theme" | "command" | "tour";

export interface Tool {
  name: string;
  where: string;                     // shown under the name
  keywords: string;                  // other words for it
  tab?: Tab; section?: string;       // jump: open the tab, unfold + scroll to the section with this heading
  needsClip?: boolean;               // the section only shows with a clip selected
  action?: Action;
}

const T = (name: string, tab: Tab, section: string, keywords: string, needsClip = false): Tool =>
  ({ name, where: `${TAB_NAMES[tab]} tab › ${section}`, keywords, tab, section, needsClip });
const A = (name: string, action: Action, keywords: string, where = "Command"): Tool => ({ name, where, keywords, action });

export const TAB_NAMES: Record<Tab, string> = {
  clip: "Clip", fx: "FX", text: "Text", blur: "Blur", beat: "Music", script: "Script", cam: "Face cam", ai: "AI", history: "History",
};

export const TOOLS: Tool[] = [
  // Clip
  T("Speed & clip timing", "clip", "Timing", "speed slow motion fast forward duration trim in out", true),
  T("Clip volume & fades", "clip", "Audio", "volume loud quiet fade in fade out gain keyframe", true),
  T("Position, size, rotation, opacity", "clip", "Transform", "move scale zoom rotate opacity transparent picture in picture pip keyframes blend mode screen multiply overlay", true),
  T("Blend modes", "clip", "Transform", "blend screen multiply overlay soft light add light leak texture", true),
  T("Crop", "clip", "Crop", "crop cut edges trim frame", true),
  T("Colour & looks", "clip", "Colour", "color colour brightness contrast saturation warmth temperature gamma look lut grade vhs cinematic", true),
  T("Auto colour fix / match cameras", "clip", "Colour", "auto color colour fix white balance exposure match camera", true),
  T("Slow push (slow zoom)", "clip", "Slow push", "ken burns slow zoom push in out documentary"),
  T("Freeze frame & reverse", "clip", "Freeze & reverse", "freeze still frame pause reverse backwards rewind"),
  T("Speed ramp", "clip", "Speed ramp", "speed ramp slow mo slow motion velocity"),
  T("Split-screen layouts", "clip", "Layout", "split screen side by side layout grid reaction"),
  T("Green screen", "clip", "Green screen", "chroma key green screen background remove"),
  // FX
  T("Transcript", "fx", "1 · Transcript", "transcribe speech to text words"),
  T("Bleep swears", "fx", "2 · Bleep swears", "censor bleep swear curse mute profanity beep"),
  T("Comedy edits (zoom, shake, sounds)", "fx", "3 · Comedy edits", "zoom shake flash sound effect sfx boom whoosh meme comedy bass boost"),
  T("Captions", "fx", "4 · Captions", "captions subtitles words karaoke emphasis style"),
  T("Audio clean-up & loudness", "fx", "5 · Audio", "normalise normalize loudness enhance voice ducking noise"),
  T("Sound design (auto whooshes)", "fx", "3 · Comedy edits", "sound design whoosh riser impact transitions auto"),
  // Text
  T("Add a title, chart or shape", "text", "Add a title or shape at the playhead", "title text lower third banner subscribe chapter arrow circle box chart ring list progress bar quote end screen timer money ticker highlighter route stamp sticker number card"),
  T("Brand kit", "text", "Brand kit", "brand logo watermark intro outro colours"),
  T("Name tags", "text", "Name tags", "name tag speaker label who is talking"),
  // Script
  T("Edit by transcript", "script", "Script", "script transcript text based editing filler words um uh retakes"),
  // Blur
  T("Blur / hide something", "blur", "Hide something", "blur pixelate hide face plate privacy censor box track"),
  // Music
  T("Background music", "beat", "Background music", "music song soundtrack background library"),
  T("Sound mixer", "beat", "Sound mixer", "mixer volume balance music level solo mute track effects level"),
  T("Beat sync", "beat", "Beat sync", "beat sync cut to the beat bpm rhythm"),
  // Face cam
  T("Face cam", "cam", "Face cam", "facecam webcam camera circle corner reaction picture in picture"),
  T("Face cam sync", "cam", "Sync", "sync line up audio face cam offset"),
  T("Face cam background removal", "cam", "Background", "remove background matte cutout face cam"),
  // AI
  T("Tell RJClip what to do", "ai", "Tell RJClip what to do", "command type instructions ai chat do it natural language"),
  T("Multicam (switch cameras)", "ai", "Multicam", "multicam multi camera angles podcast interview switch cut speaker"),
  T("Pacing checker", "ai", "Pacing checker", "pacing slow boring speed retention"),
  T("Funny-moment finder", "ai", "Funny-moment finder", "funny laugh moments highlights reaction"),
  T("Hook checker", "ai", "Hook checker", "hook intro first seconds retention"),
  T("B-roll from your clips", "ai", "B-roll from your clips", "broll b-roll cutaway footage cover"),
  T("Voiceover", "ai", "Voiceover", "voiceover narration tts record voice"),
  // History
  { name: "Saved versions", where: "History tab", keywords: "history versions restore backup autosave save compare", tab: "history" },
  // Commands
  A("Export", "export", "export render save mp4 download youtube"),
  A("Add a marker", "marker", "marker chapter flag m"),
  A("Fit the timeline", "fit", "fit zoom timeline whole"),
  A("Keyboard shortcuts", "shortcuts", "keyboard shortcuts keys hotkeys help"),
  A("Reset panel sizes", "reset-panels", "reset layout panels default size"),
  A("Show / hide the media panel", "toggle-media", "media bin panel hide show collapse"),
  A("Light / dark theme", "theme", "theme light dark mode colors appearance"),
  A("Take the tour again", "tour", "tour help guide introduction"),
];

const words = (s: string) => s.toLowerCase().replace(/[^a-z0-9 ]+/g, " ").split(/\s+/).filter(Boolean);

/** How well a tool matches what was typed (0 = not at all). Every typed word has to match
 *  something: the start of a word in the name scores most, then any word, then keywords. */
export function score(t: Tool, q: string): number {
  const qs = words(q);
  if (!qs.length) return 0;
  const name = words(t.name), kw = words(t.keywords), where = words(t.where);
  let total = 0;
  for (const w of qs) {
    let best = 0;
    for (const n of name) best = Math.max(best, n === w ? 10 : n.startsWith(w) ? 8 : n.includes(w) && w.length > 2 ? 4 : 0);
    for (const k of kw) best = Math.max(best, k === w ? 6 : k.startsWith(w) ? 5 : k.includes(w) && w.length > 3 ? 2 : 0);
    for (const k of where) best = Math.max(best, k.startsWith(w) ? 3 : 0);
    if (!best) return 0;
    total += best;
  }
  return total + (t.name.toLowerCase().startsWith(q.trim().toLowerCase()) ? 5 : 0);
}

export function searchTools(q: string, limit = 8): Tool[] {
  if (!q.trim()) return TOOLS.filter((t) => ["Tell RJClip what to do", "Sound mixer", "Add a title, chart or shape", "Captions", "Colour & looks", "Export"].includes(t.name));
  return TOOLS.map((t, i) => ({ t, s: score(t, q), i })).filter((x) => x.s > 0)
    .sort((a, b) => b.s - a.s || a.i - b.i).slice(0, limit).map((x) => x.t);
}
