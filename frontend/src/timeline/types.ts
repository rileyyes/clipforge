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
  missing_media?: string[];
}

export type MediaMap = Record<string, MediaAsset>;
