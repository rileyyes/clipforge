import type { AudioSettings, CaptionSettings, Crop, Effect, FaceCam, MediaAsset, OutputSettings, Project, Timeline } from "./timeline/types";

export class ApiError extends Error {
  constructor(message: string, public status: number, public data?: any) { super(message); }
}

const H = { "X-ClipForge": "1" };

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method,
    headers: body !== undefined ? { ...H, "Content-Type": "application/json" } : H,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (res.status === 204) return undefined as T;
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(data.error || `Request failed (${res.status})`, res.status, data);
  return data as T;
}

export interface ProjectSummary {
  id: string; name: string; updated_at: string; created_at: string; media_count: number;
  duration: number; thumbnail_media_id: string | null; clip_count: number; error?: boolean;
}

export interface Job {
  id: string; kind: string; project_id: string | null; params: Record<string, any>;
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled" | "interrupted";
  stage: string; stage_index: number; stage_count: number; progress: number | null;
  error: string | null; error_detail: string | null; result: Record<string, any>;
  created_at: string; started_at: string | null; finished_at: string | null; elapsed_s: number | null;
}

export interface ValidationReport {
  ok: boolean; checks: { check: string; ok: boolean; detail: string }[];
  file_size: number; duration: number; encoder?: string; quality?: string;
}

export interface ExportItem { file: string; size: number; modified: number; validation: ValidationReport | null }

export interface SystemInfo {
  ffmpeg: string; h264_encoder: string; workspace: string; workspace_bytes: number;
  workspace_quota_bytes: number; disk_free_bytes: number; disk_total_bytes: number;
  max_upload_bytes: number; cpu_count: number; render_cache_bytes?: number; render_cache_limit_bytes?: number;
}

export const api = {
  system: () => call<SystemInfo>("GET", "/api/system"),
  cleanup: () => call<{ freed_bytes: number }>("POST", "/api/maintenance/cleanup"),
  projects: () => call<{ projects: ProjectSummary[] }>("GET", "/api/projects").then((r) => r.projects),
  createProject: (name: string) => call<Project>("POST", "/api/projects", { name }),
  project: (id: string) => call<Project>("GET", `/api/projects/${id}`),
  /** ``facecam``: left out = unchanged, null = remove it. */
  saveTimeline: (id: string, base_edit_revision: number, timeline: Timeline, output: OutputSettings, effects?: Effect[], captions?: CaptionSettings, audio?: AudioSettings, facecam?: FaceCam | null) =>
    call<Project>("PUT", `/api/projects/${id}/timeline`, { base_edit_revision, timeline, output, effects, captions, audio, ...(facecam !== undefined ? { facecam } : {}) }),
  rename: (id: string, name: string) => call<Project>("POST", `/api/projects/${id}/rename`, { name }),
  duplicate: (id: string) => call<Project>("POST", `/api/projects/${id}/duplicate`),
  deleteProject: (id: string) => call<void>("DELETE", `/api/projects/${id}`),
  deleteMedia: (pid: string, mid: string) => call<void>("DELETE", `/api/projects/${pid}/media/${mid}`),
  /** Rebuild thumbnail + detailed waveform; with ``proxy`` also make a light 540p preview copy. */
  rebuildPreviews: (pid: string, mid: string, proxy = false) => call<Job>("POST", `/api/projects/${pid}/media/${mid}/previews`, { proxy }),
  exports: (pid: string) => call<{ exports: ExportItem[] }>("GET", `/api/projects/${pid}/exports`).then((r) => r.exports),
  startExport: (pid: string, body: { filename: string; quality: string; output: OutputSettings }) =>
    call<Job>("POST", `/api/projects/${pid}/exports`, body),
  deleteExport: (pid: string, name: string) => call<void>("DELETE", `/api/projects/${pid}/exports/${encodeURIComponent(name)}`),
  jobs: (projectId?: string) =>
    call<{ jobs: Job[] }>("GET", "/api/jobs" + (projectId ? `?project_id=${projectId}` : "")).then((r) => r.jobs),
  cancelJob: (id: string) => call<{ cancelling: boolean }>("POST", `/api/jobs/${id}/cancel`),
  retryJob: (id: string) => call<Job>("POST", `/api/jobs/${id}/retry`),
};

export interface AutoEditSettings {
  target_mode: "original" | "duration" | "percent"; target_seconds: number; target_percent: number;
  style: "balanced" | "excitement" | "information" | "reactions" | "action" | "humor" | "story";
  silence: "off" | "conservative" | "balanced" | "aggressive"; keep_opening: boolean; context: boolean;
  include: number[]; exclude: number[];
}
export interface Beat {
  id: number; start: number; end: number; kept: number; score: number; reasons: string[];
  selected: boolean; why: string; features: Record<string, number>;
}
export interface Plan {
  source_duration: number; usable_duration: number; target_duration: number; output_duration: number;
  dead_air_removed: number; beats: Beat[]; segments: { source_in: number; source_out: number; beat: number }[];
  warnings: string[]; transcript: boolean; levels: Record<string, number | null>;
}

export interface AutoStatus {
  media: { media_id: string; analyzed: boolean; has_transcript: boolean; transcript_error?: string | null; ai_rated?: number; ai_model?: string | null }[];
  transcriber: string | null; ai?: { model: string; external: boolean } | null; ai_help?: string | null;
}
export const autoedit = {
  status: (pid: string) =>
    call<AutoStatus>("GET", `/api/projects/${pid}/autoedit`),
  aiRate: (pid: string, media_id: string) => call<Job>("POST", `/api/projects/${pid}/autoedit/ai-rate`, { media_id }),
  analyze: (pid: string, media_id: string) => call<Job>("POST", `/api/projects/${pid}/autoedit/analyze`, { media_id }),
  plan: (pid: string, media_id: string, settings: AutoEditSettings) =>
    call<Plan>("POST", `/api/projects/${pid}/autoedit/plan`, { media_id, settings }),
  apply: (pid: string, media_id: string, settings: AutoEditSettings, expected_output: number, extras?: Extras) =>
    call<{ project: Project; plan: Plan; extras: ExtraNote[] }>("POST", `/api/projects/${pid}/autoedit/apply`, { media_id, settings, expected_output, extras }),
};

/** Optional finishing touches run right after the AI edit (one-click edit). */
export interface Extras {
  censor: boolean; censor_sound: "beep" | "boing" | "scratch" | "honk" | "quack" | "mute" | "custom";
  censor_sound_asset?: string | null;
  fun: "off" | "minimal" | "balanced" | "chaotic"; captions: boolean; audio_polish: boolean;
  jump_cuts?: "off" | "punch" | "blend" | "whip";
  remove_fillers?: boolean; remove_retakes?: boolean;
}

// ---------------------------------------------------------------- face cam
export const facecamApi = {
  sync: (pid: string, media_id: string, main_media_id: string) =>
    call<Job>("POST", `/api/projects/${pid}/facecam/sync`, { media_id, main_media_id }),
  faceCrop: (pid: string, media_id: string, shape: string) =>
    call<{ crop: Crop; faces_seen: number; samples: number }>("POST", `/api/projects/${pid}/facecam/face-crop`, { media_id, shape }),
  prepareCutout: (pid: string, media_id: string) => call<Job>("POST", `/api/projects/${pid}/facecam/matte`, { media_id }),
};
export interface ExtraNote { step: string; ok: boolean; detail: string }

// ---------------------------------------------------------------- My library (your own sounds & images)
export interface LibraryItem {
  id: string; kind: "sound" | "image"; name: string; source: "recorded" | "imported"; created_at: string;
  duration?: number | null; width?: number | null; height?: number | null; tags?: string[];
}
export interface BrollSuggestion { t: number; kind: "sound" | "image"; item_id: string; name: string; duration?: number | null; why: string }
async function upload<T>(path: string, body: Blob): Promise<T> {
  const res = await fetch(path, { method: "POST", headers: H, body });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(data.error || `Upload failed (${res.status})`, res.status, data);
  return data as T;
}
export const library = {
  list: () => call<{ sounds: LibraryItem[]; images: LibraryItem[] }>("GET", "/api/library"),
  addSound: (blob: Blob, name: string, recorded: boolean) =>
    upload<LibraryItem>(`/api/library/sounds?name=${encodeURIComponent(name)}${recorded ? "&recorded=1" : ""}`, blob),
  addImage: (blob: Blob, name: string) => upload<LibraryItem>(`/api/library/images?name=${encodeURIComponent(name)}`, blob),
  rename: (kind: "sound" | "image", id: string, name: string) => call<LibraryItem>("PUT", `/api/library/${kind}s/${id}`, { name }),
  setTags: (kind: "sound" | "image", id: string, tags: string[]) => call<LibraryItem>("PUT", `/api/library/${kind}s/${id}`, { tags }),
  suggest: (pid: string) => call<{ suggestions: BrollSuggestion[]; note?: string }>("POST", `/api/projects/${pid}/fx/broll/suggest`),
  remove: (kind: "sound" | "image", id: string) => call<void>("DELETE", `/api/library/${kind}s/${id}`),
  /** Copy into the project so its effects can use it (safe to repeat). */
  use: (pid: string, kind: "sound" | "image", id: string) => call<LibraryItem>("POST", `/api/projects/${pid}/fx/library`, { kind, id }),
  url: (kind: "sound" | "image", id: string) => `/api/library/${kind}s/${id}`,
};
/** URL a project plays an effect's sound from (built-in or your own). */
export const effectSoundUrl = (pid: string, sound: string | null | undefined, asset?: string | null) =>
  !sound || sound === "mute" ? null : sound === "custom" ? (asset ? `/api/projects/${pid}/fx/sounds/${asset}` : null) : `/api/sounds/${sound}.wav`;

// ---------------------------------------------------------------- version history
export interface VersionMeta {
  id: string; label: string; origin: "manual" | "auto" | "before_ai" | "before_restore" | "imported";
  created_at: string; edit_revision: number; duration: number; clips: number; effects: number; media_names: string[];
}
type Range = [number, number];
export interface Comparison {
  a_label: string; b_label: string; identical: boolean;
  a: { duration: number; clips: number; effects: number; transitions: number };
  b: { duration: number; clips: number; effects: number; transitions: number };
  sources: { media_id: string; name: string; duration: number | null; a: Range[]; b: Range[]; removed: Range[]; added: Range[]; removed_s: number; added_s: number }[];
  effects: { added: Record<string, number>; removed: Record<string, number>; changed: number };
  settings: { group: string; setting: string; a: unknown; b: unknown }[];
}
export const versions = {
  list: (pid: string) => call<{ versions: VersionMeta[] }>("GET", `/api/projects/${pid}/history`).then((r) => r.versions),
  save: (pid: string, label: string) => call<VersionMeta>("POST", `/api/projects/${pid}/history`, { label }),
  rename: (pid: string, sid: string, label: string) => call<VersionMeta>("PUT", `/api/projects/${pid}/history/${sid}`, { label }),
  remove: (pid: string, sid: string) => call<void>("DELETE", `/api/projects/${pid}/history/${sid}`),
  restore: (pid: string, sid: string) => call<Project>("POST", `/api/projects/${pid}/history/${sid}/restore`),
  compare: (pid: string, a: string, b: string) =>
    call<Comparison>("GET", `/api/projects/${pid}/history/compare?a=${encodeURIComponent(a)}&b=${encodeURIComponent(b)}`),
};

export const mediaUrl = (pid: string, mid: string) => `/api/projects/${pid}/media/${mid}/stream`;
export const thumbUrl = (pid: string, mid: string) => `/api/projects/${pid}/media/${mid}/thumbnail`;
export const waveformUrl = (pid: string, mid: string) => `/api/projects/${pid}/media/${mid}/waveform`;
export const exportUrl = (pid: string, name: string, inline = false) =>
  `/api/projects/${pid}/exports/${encodeURIComponent(name)}${inline ? "?inline=1" : ""}`;

/** Streaming upload with real byte-level progress (XHR exposes upload progress; fetch doesn't). */
export function uploadMedia(pid: string, file: File, onProgress: (f: number) => void):
  Promise<{ media: MediaAsset; job_id?: string; duplicate: boolean }> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `/api/projects/${pid}/media?filename=${encodeURIComponent(file.name)}`);
    xhr.setRequestHeader("X-ClipForge", "1");
    xhr.setRequestHeader("Content-Type", "application/octet-stream");
    xhr.upload.onprogress = (e) => { if (e.lengthComputable) onProgress(e.loaded / e.total); };
    xhr.onload = () => {
      let data: any = {};
      try { data = JSON.parse(xhr.responseText); } catch { /* ignore */ }
      if (xhr.status >= 200 && xhr.status < 300) resolve(data);
      else reject(new ApiError(data.error || (xhr.status === 413 ? "File is too large" :
        `Upload failed (server error ${xhr.status}) — check the terminal running ClipForge for details`), xhr.status));
    };
    xhr.onerror = () => reject(new ApiError("Network error during upload", 0));
    xhr.send(file);
  });
}

export function fmtTime(s: number, withFrac = true): string {
  if (!isFinite(s)) return "--:--";
  const neg = s < 0; s = Math.abs(s);
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  const ss = withFrac ? sec.toFixed(2).padStart(5, "0") : Math.floor(sec).toString().padStart(2, "0");
  return (neg ? "-" : "") + (h ? `${h}:${String(m).padStart(2, "0")}:${ss}` : `${m}:${ss}`);
}

export function fmtBytes(n: number): string {
  if (!n) return "0 B";
  const u = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.min(u.length - 1, Math.floor(Math.log(n) / Math.log(1024)));
  return `${(n / 1024 ** i).toFixed(i ? 1 : 0)} ${u[i]}`;
}
