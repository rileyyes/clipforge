"""Upload to YouTube with your own Google account (free; nothing goes through anyone else).

Setup, once (free, ~5 minutes; see docs/YOUTUBE.md):
  Google Cloud Console → new project → enable "YouTube Data API v3" → OAuth consent screen
  (External, add yourself as a test user) → Credentials → OAuth client ID → *Desktop app*
  → download the JSON → RJClip → Publish → "Connect YouTube" → choose that file.

* Sign-in uses Google's installed-app flow with PKCE and a one-time ``state``; Google
  redirects back to RJClip on 127.0.0.1. Only the upload + read-only scopes are asked
  for. The refresh token is stored in ``<workspace>/secrets`` (owner-only permissions)
  and never sent to the browser.
* Uploads are *resumable*: 8 MB chunks, retries with back-off on 5xx/network errors,
  and, after an interruption, asking Google how much it already has before continuing.
* Nothing is uploaded unless you press Upload and confirm; the default privacy is
  **private**. Scheduling (publish at) requires private, as YouTube requires.
* Quota: YouTube gives each project 10,000 units/day; an upload costs ~1,600, so about
  6 uploads a day per Google project.

Endpoints are overridable (RJCLIP_GOOGLE_*), which the tests use to talk to a fake
Google. This module is contract-tested only; it has not been run against real YouTube
from the development environment.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable, Optional

from .storage import atomic_write_json

AUTH_URL = os.environ.get("RJCLIP_GOOGLE_AUTH_URL", "https://accounts.google.com/o/oauth2/v2/auth")
TOKEN_URL = os.environ.get("RJCLIP_GOOGLE_TOKEN_URL", "https://oauth2.googleapis.com/token")
REVOKE_URL = os.environ.get("RJCLIP_GOOGLE_REVOKE_URL", "https://oauth2.googleapis.com/revoke")
API_URL = os.environ.get("RJCLIP_YOUTUBE_API_URL", "https://www.googleapis.com/youtube/v3")
UPLOAD_URL = os.environ.get("RJCLIP_YOUTUBE_UPLOAD_URL", "https://www.googleapis.com/upload/youtube/v3")
SCOPES = ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube.readonly"]
CHUNK = 8 * 1024 * 1024  # multiple of 256 KiB, as the resumable protocol requires
TIMEOUT = 60


class YouTubeError(RuntimeError):
    pass


def _urls() -> dict:  # read at call time so tests (and power users) can point elsewhere
    return {"auth": os.environ.get("RJCLIP_GOOGLE_AUTH_URL", AUTH_URL),
            "token": os.environ.get("RJCLIP_GOOGLE_TOKEN_URL", TOKEN_URL),
            "revoke": os.environ.get("RJCLIP_GOOGLE_REVOKE_URL", REVOKE_URL),
            "api": os.environ.get("RJCLIP_YOUTUBE_API_URL", API_URL),
            "upload": os.environ.get("RJCLIP_YOUTUBE_UPLOAD_URL", UPLOAD_URL)}


def _req(method: str, url: str, *, data: Optional[bytes] = None, headers: Optional[dict] = None,
         timeout: float = TIMEOUT) -> tuple[int, dict, bytes]:
    r = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def _err_message(body: bytes, fallback: str) -> str:
    try:
        d = json.loads(body)
        e = d.get("error")
        if isinstance(e, dict):
            reason = (e.get("errors") or [{}])[0].get("reason", "")
            msg = e.get("message", fallback)
            if reason == "quotaExceeded":
                return "YouTube's daily upload quota for your Google project is used up — try again tomorrow."
            if reason in ("uploadLimitExceeded",):
                return "YouTube says this channel has hit its upload limit for now."
            return msg
        return d.get("error_description") or str(e) or fallback
    except ValueError:
        return fallback


class YouTube:
    def __init__(self, workspace: Path):
        self.dir = workspace / "secrets"
        self.dir.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.dir, 0o700)
        except OSError:
            pass
        self.client_file = self.dir / "youtube_client.json"
        self.token_file = self.dir / "youtube_token.json"
        self.pending: dict[str, dict] = {}  # state -> {verifier, redirect_uri, at}

    # ---------------------------------------------------------------- client + status
    def set_client(self, raw: bytes) -> dict:
        try:
            d = json.loads(raw)
        except ValueError as exc:
            raise YouTubeError("That isn't the JSON file Google gives you for an OAuth client.") from exc
        c = d.get("installed") or d.get("web")
        if not isinstance(c, dict) or not c.get("client_id") or not c.get("client_secret"):
            raise YouTubeError("This file has no OAuth client in it. Create a *Desktop app* OAuth client and download its JSON.")
        if "web" in d and "installed" not in d:
            raise YouTubeError("This is a *Web application* client. Create a *Desktop app* client instead (it allows signing in via 127.0.0.1).")
        client = {"client_id": str(c["client_id"]), "client_secret": str(c["client_secret"])}
        self._write(self.client_file, client)
        return {"client_id": client["client_id"][:12] + "…"}

    def _write(self, path: Path, data: dict) -> None:
        atomic_write_json(path, data, keep_backup=False)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass

    def client(self) -> Optional[dict]:
        if not self.client_file.exists():
            return None
        return json.loads(self.client_file.read_bytes())

    def token(self) -> Optional[dict]:
        if not self.token_file.exists():
            return None
        return json.loads(self.token_file.read_bytes())

    def status(self) -> dict:
        tok = self.token()
        return {"client_configured": self.client() is not None, "connected": bool(tok and tok.get("refresh_token")),
                "channel": (tok or {}).get("channel")}

    # ---------------------------------------------------------------- sign-in
    def auth_url(self, redirect_uri: str) -> str:
        c = self.client()
        if c is None:
            raise YouTubeError("Add your Google OAuth client file first.")
        verifier = secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        state = secrets.token_urlsafe(24)
        now = time.time()
        self.pending = {k: v for k, v in self.pending.items() if now - v["at"] < 900}
        self.pending[state] = {"verifier": verifier, "redirect_uri": redirect_uri, "at": now}
        q = {"client_id": c["client_id"], "redirect_uri": redirect_uri, "response_type": "code",
             "scope": " ".join(SCOPES), "access_type": "offline", "prompt": "consent", "state": state,
             "code_challenge": challenge, "code_challenge_method": "S256"}
        return _urls()["auth"] + "?" + urllib.parse.urlencode(q)

    def finish(self, state: str, code: str) -> dict:
        p = self.pending.pop(state, None)  # one-time: a replayed or forged callback fails here
        if p is None or time.time() - p["at"] > 900:
            raise YouTubeError("This sign-in link expired or wasn't started here. Press Connect again.")
        c = self.client()
        if c is None:
            raise YouTubeError("The OAuth client was removed during sign-in.")
        body = urllib.parse.urlencode({"code": code, "client_id": c["client_id"], "client_secret": c["client_secret"],
                                       "redirect_uri": p["redirect_uri"], "grant_type": "authorization_code",
                                       "code_verifier": p["verifier"]}).encode()
        st, _h, data = _req("POST", _urls()["token"], data=body,
                            headers={"Content-Type": "application/x-www-form-urlencoded"})
        if st != 200:
            raise YouTubeError("Google didn't accept the sign-in: " + _err_message(data, f"HTTP {st}"))
        tok = json.loads(data)
        if not tok.get("refresh_token"):
            raise YouTubeError("Google didn't return a refresh token. Remove RJClip's access in your Google "
                               "account settings, then connect again.")
        tok["expires_at"] = time.time() + float(tok.get("expires_in", 3600)) - 60
        self._write(self.token_file, tok)
        try:
            tok["channel"] = self.channel()
            self._write(self.token_file, tok)
        except YouTubeError:
            pass
        return self.status()

    def access_token(self) -> str:
        tok = self.token()
        if not tok or not tok.get("refresh_token"):
            raise YouTubeError("Connect your YouTube account first.")
        if tok.get("access_token") and tok.get("expires_at", 0) > time.time():
            return tok["access_token"]
        c = self.client()
        if c is None:
            raise YouTubeError("The OAuth client file is missing; add it again.")
        body = urllib.parse.urlencode({"client_id": c["client_id"], "client_secret": c["client_secret"],
                                       "refresh_token": tok["refresh_token"], "grant_type": "refresh_token"}).encode()
        st, _h, data = _req("POST", _urls()["token"], data=body,
                            headers={"Content-Type": "application/x-www-form-urlencoded"})
        if st != 200:
            if st in (400, 401):
                raise YouTubeError("Your YouTube sign-in expired or was revoked. Connect again.")
            raise YouTubeError("Couldn't refresh the YouTube sign-in: " + _err_message(data, f"HTTP {st}"))
        new = json.loads(data)
        tok.update(access_token=new["access_token"], expires_at=time.time() + float(new.get("expires_in", 3600)) - 60)
        self._write(self.token_file, tok)
        return tok["access_token"]

    def channel(self) -> Optional[dict]:
        st, _h, data = _req("GET", _urls()["api"] + "/channels?part=snippet&mine=true",
                            headers={"Authorization": "Bearer " + self.access_token()})
        if st != 200:
            raise YouTubeError(_err_message(data, f"HTTP {st}"))
        items = json.loads(data).get("items") or []
        return {"id": items[0]["id"], "title": items[0]["snippet"]["title"]} if items else None

    def disconnect(self) -> None:
        tok = self.token()
        if tok and tok.get("refresh_token"):
            try:
                _req("POST", _urls()["revoke"], data=urllib.parse.urlencode({"token": tok["refresh_token"]}).encode(),
                     headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=15)
            except OSError:
                pass  # removing it locally is what matters
        self.token_file.unlink(missing_ok=True)

    # ---------------------------------------------------------------- upload
    def upload(self, video: Path, meta: dict, thumbnail: Optional[Path] = None,
               on_progress: Optional[Callable[[float], None]] = None, cancel=None,
               sleep: Callable[[float], None] = time.sleep) -> dict:
        from .ffmpeg import Cancelled
        size = video.stat().st_size
        auth = {"Authorization": "Bearer " + self.access_token()}
        st, h, data = _req("POST", _urls()["upload"] + "/videos?uploadType=resumable&part=snippet,status",
                           data=json.dumps(meta).encode(),
                           headers={**auth, "Content-Type": "application/json; charset=UTF-8",
                                    "X-Upload-Content-Length": str(size), "X-Upload-Content-Type": "video/mp4"})
        if st != 200 or not _header(h, "location"):
            raise YouTubeError("YouTube refused the upload: " + _err_message(data, f"HTTP {st}"))
        session = _header(h, "location")
        offset, failures, result = 0, 0, None
        with open(video, "rb") as fh:
            while result is None:
                if cancel is not None and cancel.is_set():
                    raise Cancelled("cancelled")
                fh.seek(offset)
                chunk = fh.read(CHUNK)
                end = offset + len(chunk) - 1
                try:
                    st, h, data = _req("PUT", session, data=chunk, timeout=300, headers={
                        "Content-Length": str(len(chunk)), "Content-Range": f"bytes {offset}-{end}/{size}"})
                except OSError:
                    st, h, data = 0, {}, b""
                if st in (200, 201):
                    result = json.loads(data)
                elif st == 308:  # "resume incomplete": continue from what Google has
                    offset = _received(h)
                    failures = 0
                elif st in (0, 500, 502, 503, 504):
                    failures += 1
                    if failures > 6:
                        raise YouTubeError("The upload kept failing (network or YouTube trouble). Try again later — "
                                           "nothing was published.")
                    sleep(min(60, 2 ** failures))
                    offset = self._query_offset(session, size)
                    if offset is None:  # Google already has everything
                        result = self._finish_query(session, size)
                else:
                    raise YouTubeError("YouTube stopped the upload: " + _err_message(data, f"HTTP {st}"))
                if on_progress:
                    on_progress(min(0.99, offset / max(1, size)) if result is None else 1.0)
        vid = result.get("id")
        out = {"video_id": vid, "url": f"https://youtu.be/{vid}" if vid else None,
               "privacy": result.get("status", {}).get("privacyStatus"), "thumbnail": None}
        if thumbnail is not None and vid:
            out["thumbnail"] = self._thumbnail(vid, thumbnail)
        return out

    def _query_offset(self, session: str, size: int) -> Optional[int]:
        try:
            st, h, _d = _req("PUT", session, data=b"", headers={"Content-Length": "0", "Content-Range": f"bytes */{size}"})
        except OSError:
            return 0
        if st in (200, 201):
            return None
        return _received(h) if st == 308 else 0

    def _finish_query(self, session: str, size: int) -> dict:
        st, _h, data = _req("PUT", session, data=b"", headers={"Content-Length": "0", "Content-Range": f"bytes */{size}"})
        return json.loads(data)

    def _thumbnail(self, vid: str, path: Path) -> str:
        if path.stat().st_size > 2 * 1024 * 1024:
            return "skipped: thumbnails must be under 2 MB"
        mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
        st, _h, data = _req("POST", _urls()["upload"] + f"/thumbnails/set?videoId={urllib.parse.quote(vid)}",
                            data=path.read_bytes(), headers={"Authorization": "Bearer " + self.access_token(),
                                                             "Content-Type": mime})
        if st == 200:
            return "set"
        return "not set: " + _err_message(data, f"HTTP {st}") + (
            " (custom thumbnails need a verified channel)" if st == 403 else "")


def _header(h: dict, name: str) -> Optional[str]:
    for k, v in h.items():
        if k.lower() == name:
            return v
    return None


def _received(h: dict) -> int:
    rng = _header(h, "range")  # "bytes=0-12345"
    if not rng:
        return 0
    try:
        return int(rng.split("-")[1]) + 1
    except (IndexError, ValueError):
        return 0


def metadata(draft: dict) -> dict:
    """YouTube's snippet/status from a saved draft; chapters are written into the description."""
    desc = draft.get("description", "")
    ch = draft.get("chapters") or []
    if ch and "0:00" not in desc:
        from .publish import fmt_ts
        desc = (desc + "\n\n" if desc else "") + "\n".join(f"{fmt_ts(c['t'])} {c['title']}" for c in ch)
    status = {"privacyStatus": draft.get("privacy", "private"),
              "selfDeclaredMadeForKids": bool(draft.get("made_for_kids", False))}
    if draft.get("publish_at"):
        status["privacyStatus"] = "private"  # YouTube publishes it at that time
        status["publishAt"] = draft["publish_at"]
    return {"snippet": {"title": draft.get("title") or "Untitled", "description": desc[:5000],
                        "tags": draft.get("tags") or [], "categoryId": draft.get("category_id", "22")},
            "status": status}
