// Mirrors backend/app/schema.py (schema_version 1). Keep in sync.

export type TrackKind = "video" | "audio";

export interface Transform {
  x: number;
  y: number;
  scale: number;
  rotation: number;   // degrees, clockwise
  opacity?: number;   // 0..1
}
export interface Chroma { color: string; similarity: number; blend: number }
export interface Crop { left: number; right: number; top: number; bottom: number }
export const LOOKS = ["none", "warm", "cool", "bw", "vintage", "vivid", "faded", "cinematic", "noir",
  "horror", "vhs", "film", "vignette", "letterbox"] as const;
export type Look = (typeof LOOKS)[number];
export interface ColorAdjust { brightness: number; contrast: number; saturation: number; gamma: number; temperature: number; look: Look }
export type KfProp = "scale" | "x" | "y" | "rotation" | "opacity" | "volume";
/** Value at a moment of the SOURCE media (seconds); ease shapes the move to the next keyframe. */
export interface Keyframe { t: number; v: number; ease?: "linear" | "ease" | "hold" }

export interface Clip {
  id: string;
  media_id: string;
  start: number; // timeline seconds
  source_in: number;
  source_out: number;
  speed: number;
  volume: number;
  transform: Transform;
  crop?: Crop;
  color?: ColorAdjust;
  /** green screen: make this colour see-through */
  chroma?: Chroma | null;
  keyframes?: Partial<Record<KfProp, Keyframe[]>>;
  link_id: string | null;
  label?: string | null;
  transition_in?: Transition | null; // video clips: into this clip from the one before it
  fade_in?: number;                  // seconds (video: from black, audio: volume)
  fade_out?: number;
}

export const TRANSITIONS = [
  ["crossfade", "Crossfade"], ["dip_black", "Dip to black"], ["dip_white", "Dip to white (flash)"],
  ["wipe_left", "Wipe left"], ["wipe_right", "Wipe right"], ["wipe_up", "Wipe up"], ["wipe_down", "Wipe down"],
  ["slide_left", "Slide left"], ["slide_right", "Slide right"], ["slide_up", "Slide up"], ["slide_down", "Slide down"],
  ["smooth_left", "Smooth left"], ["smooth_right", "Smooth right"], ["cover_left", "Cover left"], ["reveal_right", "Reveal right"],
  ["circle_open", "Circle open"], ["circle_close", "Circle close"], ["radial", "Radial sweep"], ["zoom_in", "Zoom in"],
  ["pixelize", "Pixelize"], ["blur", "Blur"],
  ["whip_left", "Whip pan left"], ["whip_right", "Whip pan right"], ["spin", "Spin"], ["glitch", "Glitch"],
  ["rgb_split", "RGB split"], ["light_leak", "Light leak"], ["zoom_blur", "Zoom blur"],
  ["flash_cut", "Flash cut"], ["shake_cut", "Shake cut"],
] as const;
export type TransitionKind = (typeof TRANSITIONS)[number][0];
export interface Transition { kind: TransitionKind; duration: number }

export interface Track {
  id: string;
  kind: TrackKind;
  name: string;
  muted: boolean;
  hidden: boolean;
  locked: boolean;
  /** audio: music ducks under dialogue; everything ducks under narration (Phase 18) */
  role?: "dialogue" | "music" | "narration";
  /** name tag shown while this track is talking (Phase 18) */
  tag?: string; tag_color?: string;
  clips: Clip[];
}

export type TitleTemplate = "lower_third" | "big_title" | "top_banner" | "subscribe" | "chapter" | "pop_text" | "arrow" | "circle" | "box"
  | "count_card" | "tally" | "number_card" | "sticker";
export interface Title {
  id: string; start: number; duration: number; template: TitleTemplate; text: string; subtext: string;
  color: string; accent: string; align: "left" | "center" | "right"; size: number;
  /** pop_text and shapes: centre (fractions of the frame), rotation (degrees, clockwise), in-animation */
  x?: number; y?: number; rotation?: number; anim?: TitleAnim;
  /** Phase 18: font id (null = default), outline/shadow (null = the template's), glow (0 = off), number_card number */
  font?: string | null; stroke?: number | null; stroke_color?: string; shadow?: number | null;
  glow?: number; glow_color?: string; number?: number;
}
/** The style part of a title, saved as a preset */
export type TextStyle = Pick<Title, "font" | "color" | "accent" | "stroke" | "stroke_color" | "shadow" | "glow" | "glow_color"> & { name: string };
export type TitleAnim = "none" | "pop" | "typewriter" | "slide_up" | "bounce";
export const FREE_TEMPLATES: TitleTemplate[] = ["pop_text", "sticker", "arrow", "circle", "box"];

export interface BlurKey { t: number; x: number; y: number; w: number; h: number }  // timeline s; frame fractions
export interface Blur {
  id: string; start: number; duration: number; mode: "blur" | "pixelate" | "black"; shape: "rect" | "ellipse";
  strength: number; keys: BlurKey[];
}

/** A named point on the timeline (press M). Can become YouTube chapters on the Publish page. */
export interface Marker {
  id: string;
  t: number;
  label: string;
  color: string;
}

export const MARKER_COLORS = ["#ffb703", "#4cc9f0", "#2bb38a", "#ff5a3c", "#b388ff"];

export interface Timeline {
  tracks: Track[];
  titles?: Title[];
  blurs?: Blur[];
  markers?: Marker[];
  counters?: Counter[];
  name_tags?: NameTags;
}

/** An on-screen tally (Phase 18). Each enabled "count" effect for it adds one when it plays. */
export interface Counter {
  id: string; label: string; start_value: number; start: number; end: number | null;
  x: number; y: number; size: number; color: string; accent: string; font: string | null;
}
export interface NameTags { enabled: boolean; corner: "tl" | "tr" | "bl" | "br"; size: number; only_talking: boolean }

export interface MediaAsset {
  id: string;
  original_name: string;
  stored_name: string;
  kind: "video" | "audio";
  duration: number;
  size_bytes: number;
  sha256?: string | null;
  container: string;
  has_video: boolean;
  has_audio: boolean;
  width?: number | null;
  height?: number | null;
  fps?: number | null;
  variable_frame_rate: boolean;
  video_codec?: string | null;
  audio_codec?: string | null;
  sample_rate?: number | null;
  channels?: number | null;
  thumbnail?: string | null;
  proxy?: string | null;
  waveform?: string | null;
  imported_at: string;
}

export interface OutputSettings {
  width: number;
  height: number;
  fps: number;
  fit_mode: "fit" | "fill";
}

export type EffectKind = "censor" | "zoom" | "shake" | "flash" | "text" | "sfx" | "image" | "count" | "bass";
export type Sound = "beep" | "boing" | "scratch" | "honk" | "quack" | "mute" | "boom" | "whoosh" | "ding" | "pop" | "airhorn" | "custom";

export interface Effect {
  id: string; kind: EffectKind; media_id: string; source_time: number; duration: number;
  enabled: boolean; origin: "auto" | "user"; sound: Sound | null; volume: number;
  /** sound === "custom": id of a sound from My library (copied into the project) */
  sound_asset?: string | null;
  text: string | null; word: string | null; context: string | null; confidence: number | null; needs_review: boolean;
  scale: number; intensity: number; x: number; y: number; size: number; color: string; asset: string | null;
  /** kind === "count": which counter goes up */
  counter?: string | null;
}

export interface CaptionSettings {
  enabled: boolean; style: "bold_pop" | "clean" | "highlight"; position: "bottom" | "middle" | "top";
  size: number; color: string; highlight: string; max_words: number; uppercase: boolean;
  font?: string | null;
}

export interface AudioSettings {
  normalize: boolean; target_lufs: number; noise_reduction: "off" | "light" | "medium" | "strong";
  enhance_voice: boolean; ducking: "off" | "light" | "medium" | "strong";
}

export interface CamRange { start: number; end: number }   // main recording, source seconds
export interface CamBox { x: number; y: number; w: number; h: number }  // fractions of the frame
export type CamCorner = "top_left" | "top_right" | "bottom_left" | "bottom_right" | "custom";
export interface FaceCam {
  enabled: boolean; media_id: string; main_media_id: string; offset: number;
  corner: CamCorner; size: number; margin: number; box: CamBox; crop: Crop;
  shape: "rect" | "rounded" | "circle"; border: number; border_color: string; shadow: boolean;
  remove_bg: boolean; hidden: CamRange[]; full: CamRange[];
}

export interface Project {
  schema_version: number;
  id: string;
  name: string;
  revision: number;
  edit_revision: number;
  created_at: string;
  updated_at: string;
  media: MediaAsset[];
  timeline: Timeline;
  output: OutputSettings;
  effects: Effect[];
  captions: CaptionSettings;
  audio: AudioSettings;
  facecam?: FaceCam | null;
  /** brand kit logo on the whole video (Phase 15) */
  watermark?: { file: string; corner: "tl" | "tr" | "bl" | "br"; size: number; opacity: number } | null;
  missing_media?: string[];
  /** media ids whose background-removal mask is ready */
  mattes?: string[];
}

export type MediaMap = Record<string, MediaAsset>;
