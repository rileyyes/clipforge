// Mirrors backend/app/schema.py (schema_version 1). Keep in sync.

export type TrackKind = "video" | "audio";

export interface Transform {
  x: number;
  y: number;
  scale: number;
  rotation: number;
}

export interface Clip {
  id: string;
  media_id: string;
  start: number; // timeline seconds
  source_in: number;
  source_out: number;
  speed: number;
  volume: number;
  transform: Transform;
  link_id: string | null;
  label?: string | null;
}

export interface Track {
  id: string;
  kind: TrackKind;
  name: string;
  muted: boolean;
  hidden: boolean;
  locked: boolean;
  clips: Clip[];
}

export interface Timeline {
  tracks: Track[];
}

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

export type EffectKind = "censor" | "zoom" | "shake" | "flash" | "text" | "sfx" | "image";
export type Sound = "beep" | "boing" | "scratch" | "honk" | "quack" | "mute" | "boom" | "whoosh" | "ding" | "pop" | "airhorn";

export interface Effect {
  id: string; kind: EffectKind; media_id: string; source_time: number; duration: number;
  enabled: boolean; origin: "auto" | "user"; sound: Sound | null; volume: number;
  text: string | null; word: string | null; context: string | null; confidence: number | null; needs_review: boolean;
  scale: number; intensity: number; x: number; y: number; size: number; color: string; asset: string | null;
}

export interface CaptionSettings {
  enabled: boolean; style: "bold_pop" | "clean" | "highlight"; position: "bottom" | "middle" | "top";
  size: number; color: string; highlight: string; max_words: number; uppercase: boolean;
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
  missing_media?: string[];
}

export type MediaMap = Record<string, MediaAsset>;
