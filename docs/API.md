# API reference

Base URL `http://127.0.0.1:8765`. JSON in/out. Every non-GET request must send header **`X-ClipForge: 1`**. Errors are `{"error": "message"}` with a meaningful status (400, 403, 404, 409, 413, 415, 422, 507).

## System
| Method | Path | Description |
|---|---|---|
| GET | `/api/health` | liveness |
| GET | `/api/system` | FFmpeg version, chosen H.264 encoder, workspace, storage, limits |
| POST | `/api/maintenance/cleanup` | remove stale work dirs and partial files → `{freed_bytes}` |

## Projects
| Method | Path | Body | Description |
|---|---|---|---|
| GET | `/api/projects` | | summaries, newest first |
| POST | `/api/projects` | `{name}` | create (with V1, V2, A1, A2) |
| GET | `/api/projects/{pid}` | | full project + `missing_media` |
| PUT | `/api/projects/{pid}/timeline` | `{base_edit_revision, timeline, output}` | validated save; **409** if `base_edit_revision` is stale |
| POST | `/api/projects/{pid}/rename` | `{name}` | |
| POST | `/api/projects/{pid}/duplicate` | | copies media + timeline |
| DELETE | `/api/projects/{pid}` | | 409 while jobs are running |

## Media
| Method | Path | Description |
|---|---|---|
| POST | `/api/projects/{pid}/media?filename=x.mp4` | raw file body (streamed). → `201 {media, job_id}` or `200 {media, duplicate: true}`. 413 too large, 415 unsupported or unreadable. |
| GET | `/api/projects/{pid}/media/{mid}/stream` | proxy if present else original. Supports HTTP Range. |
| GET | `/api/projects/{pid}/media/{mid}/thumbnail` | JPEG |
| GET | `/api/projects/{pid}/media/{mid}/waveform` | `{peaks_per_second: 20, peaks: [0..255]}` |
| DELETE | `/api/projects/{pid}/media/{mid}` | 409 if used on the timeline |

## Exports
| Method | Path | Body | Description |
|---|---|---|---|
| POST | `/api/projects/{pid}/exports` | `{filename, quality: draft\|standard\|high, output?, encoder?: auto\|libx264}` | starts a render job → 202 job |
| GET | `/api/projects/{pid}/exports` | | files + validation reports |
| GET | `/api/projects/{pid}/exports/{name}` | | download (`?inline=1` to stream) |
| POST | `/api/projects/{pid}/exports/{name}/validate` | | re-run validation |
| DELETE | `/api/projects/{pid}/exports/{name}` | | |

## Jobs
| Method | Path | Description |
|---|---|---|
| GET | `/api/jobs?project_id=` | newest first |
| GET | `/api/jobs/{jid}` | `status` (queued/running/succeeded/failed/cancelled/interrupted), `stage`, `stage_index/count`, `progress` (0–1 or null = not measurable), `error`, `error_detail`, `result` |
| POST | `/api/jobs/{jid}/cancel` | |
| POST | `/api/jobs/{jid}/retry` | failed/cancelled/interrupted only |

The project schema is in `backend/app/schema.py`.
