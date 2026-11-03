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

## AI Auto Editor
| Method | Path | Body | Description |
|---|---|---|---|
| GET | `/api/projects/{pid}/autoedit` | | per-media analysis status, installed transcriber |
| POST | `/api/projects/{pid}/autoedit/analyze` | `{media_id, transcribe?}` | starts (or returns the running) analysis job |
| POST | `/api/projects/{pid}/autoedit/plan` | `{media_id, settings}` | → plan: durations, warnings, `beats` (score, reasons, selected, why), `segments` (EDL). 409 if not analysed. |
| POST | `/api/projects/{pid}/autoedit/apply` | `{media_id, settings, expected_output}` | recomputes the plan server-side (client EDLs are never trusted), refuses with 409 if it differs from what was reviewed, backs up the old timeline, writes linked V1/A1 clips |

`settings`: `target_mode` (`original`/`duration`/`percent`), `target_seconds`, `target_percent`, `style` (`balanced`/`excitement`/`information`/`reactions`/`action`/`humor`/`story`), `silence` (`off`/`conservative`/`balanced`/`aggressive`), `keep_opening`, `context`, `include[]`, `exclude[]` (beat ids).

## Effects & captions (Phase 4)
| Method | Path | Description |
|---|---|---|
| GET | `/api/projects/{pid}/fx/status` | transcriber installed?, transcript coverage of the edit, font |
| POST | `/api/projects/{pid}/transcribe` | `{media_ids?}` → transcription job (409 + install help if not installed) |
| GET | `/api/projects/{pid}/transcript` | words surviving in the final edit (timeline times) |
| POST | `/api/projects/{pid}/fx/censor/suggest` | `{sound, level, custom[], allow[], padding}` → bleep effects (not saved) |
| POST | `/api/projects/{pid}/fx/fun/suggest` | `{intensity}` → zoom/shake/text/sfx effects (not saved) |
| GET | `/api/projects/{pid}/captions.srt` | SRT of the final edit (censored words masked) |
| GET/POST | `/api/projects/{pid}/fx/images`, GET `/fx/images/{id}` | your pop-up images |
| GET | `/api/sounds/{name}.wav` | preview a synthesised sound |

Effects and caption settings are saved with `PUT /timeline` (`effects`, `captions`). Project schema v2. v1 projects migrate automatically.

## Thumbnail Maker (`/api/projects/{pid}/thumbnails`)
| Method | Path | Description |
|---|---|---|
| GET | `` | providers (no keys), context, cached analysis for the current edit, saved designs |
| POST | `/analyze` | job: frames + summary of the final edit |
| POST | `/concepts` | `{context, seed}` → 3 concepts + headlines, or `{needs_context}` |
| POST | `/generate` | `{concept, use_references, consent_external}` → artwork job. 409 no provider, 428 consent needed |
| POST | `/designs` | `{concept, workflow, art_asset?}` → new design |
| GET/PUT/DELETE | `/designs/{did}` | draft (+ staleness) / autosave draft / delete |
| POST | `/designs/{did}/versions`, `/versions/{vid}/restore`; PUT `/versions/{vid}` | immutable versions, restore into draft, rename |
| POST | `/designs/{did}/duplicate` | copy |
| POST | `/designs/{did}/export?format=jpg\|png[&version=]` | raw image body → validated + saved (422 with report if invalid) |
| POST | `/refine` | `{design, instruction}` → updated design, notes, optional regeneration prompt |
| POST | `/frame?t=` · `/assets` | frame at a timeline time · upload an image |
| GET | `/assets/{aid}` · `/exports` · `/exports/{name}` | files |

## Jobs
| Method | Path | Description |
|---|---|---|
| GET | `/api/jobs?project_id=` | newest first |
| GET | `/api/jobs/{jid}` | `status` (queued/running/succeeded/failed/cancelled/interrupted), `stage`, `stage_index/count`, `progress` (0–1 or null = not measurable), `error`, `error_detail`, `result` |
| POST | `/api/jobs/{jid}/cancel` | |
| POST | `/api/jobs/{jid}/retry` | failed/cancelled/interrupted only |

The project schema is in `backend/app/schema.py`.
