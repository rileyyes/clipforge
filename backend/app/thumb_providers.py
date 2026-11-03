"""AI provider abstraction for the Thumbnail Maker.

Image providers
* ``openai``  — OpenAI Images API (``gpt-image-1`` by default). Generation, and
                generation guided by reference images via the edits endpoint.
                External service: needs ``OPENAI_API_KEY``; prompts (and reference
                frames, only with consent) leave your computer. Paid per image.
* ``sdwebui`` — Stable Diffusion WebUI API (AUTOMATIC1111 / Forge) running on your
                machine: ``txt2img`` and ``img2img``. Free and private when local.

Text model (creative director / refinement / optional vision)
* OpenAI-compatible ``/chat/completions`` — OpenAI, or a local Ollama / LM Studio
  server via ``CLIPFORGE_LLM_BASE_URL``.

Configuration is environment-only (keys never reach the browser). Provider base
URLs come from configuration, never from user input (no SSRF).

Testing status: request/response handling is covered by contract tests against
a local fake server that mimics each documented API. The real services were NOT
reachable from the build environment and have not been exercised end-to-end.
"""
from __future__ import annotations

import base64
import json
import os
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field
from typing import Optional

from . import ffmpeg as ff

TIMEOUT_S = 180


class ProviderError(RuntimeError):
    def __init__(self, message: str, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


def _is_local(url: str) -> bool:
    host = urllib.parse.urlparse(url).hostname or ""
    return host in ("localhost", "127.0.0.1", "::1") or host.endswith(".local")


def _http(method: str, url: str, *, headers: dict, body: Optional[bytes], timeout: float,
          cancel: Optional[threading.Event] = None) -> dict:
    """JSON HTTP call run in a worker thread so a cancel request returns promptly.
    (A provider may still finish — and bill — a request already sent.)"""
    box: dict = {}

    def run():
        req = urllib.request.Request(url, data=body, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                box["data"] = resp.read()
        except urllib.error.HTTPError as e:
            raw = e.read()[:4000]
            try:
                msg = json.loads(raw).get("error", {})
                msg = msg.get("message") if isinstance(msg, dict) else msg
            except ValueError:
                msg = raw.decode(errors="replace")
            box["err"] = (e.code, str(msg or e.reason))
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            box["neterr"] = str(getattr(e, "reason", e))

    t = threading.Thread(target=run, daemon=True)
    t.start()
    while t.is_alive():
        t.join(0.25)
        if cancel is not None and cancel.is_set():
            raise ff.Cancelled("cancelled by user")
    if "neterr" in box:
        raise ProviderError(f"Couldn't reach the provider ({box['neterr']}). Check the URL / your connection.",
                            retryable=True)
    if "err" in box:
        code, msg = box["err"]
        if code in (401, 403):
            raise ProviderError("The provider rejected the API key (check it in your environment settings).")
        if code == 429:
            raise ProviderError(f"Rate limit or quota reached at the provider: {msg}", retryable=True)
        if code >= 500:
            raise ProviderError(f"The provider had an error ({code}): {msg}", retryable=True)
        raise ProviderError(f"The provider refused the request ({code}): {msg}")
    try:
        return json.loads(box.get("data") or b"{}")
    except ValueError as e:
        raise ProviderError("The provider returned something that isn't JSON.") from e


def _multipart(fields: dict[str, str], files: list[tuple[str, str, bytes, str]]) -> tuple[bytes, str]:
    boundary = "----clipforge" + uuid.uuid4().hex
    out = bytearray()
    for k, v in fields.items():
        out += f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode()
    for name, filename, data, ctype in files:
        out += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"; filename=\"{filename}\"\r\n"
                f"Content-Type: {ctype}\r\n\r\n").encode() + data + b"\r\n"
    out += f"--{boundary}--\r\n".encode()
    return bytes(out), f"multipart/form-data; boundary={boundary}"


# ---------------------------------------------------------------- image providers
@dataclass
class ImageProvider:
    id: str
    label: str
    model: str
    base_url: str
    external: bool
    caps: set = field(default_factory=set)  # {"generate", "reference"}
    note: str = ""

    def info(self) -> dict:
        return {"id": self.id, "label": self.label, "model": self.model, "external": self.external,
                "capabilities": sorted(self.caps), "note": self.note,
                "tested_against_real_service": False}

    def generate(self, prompt: str, negative: str, refs: list[bytes],
                 cancel: Optional[threading.Event] = None) -> bytes:
        raise NotImplementedError


class OpenAIImages(ImageProvider):
    def __init__(self, key: str, base_url: str, model: str, quality: str):
        super().__init__("openai", "OpenAI Images", model, base_url.rstrip("/"), not _is_local(base_url),
                         {"generate", "reference"},
                         "Paid per image. Prompts, and reference frames you approve, are sent to OpenAI.")
        self._key, self.quality = key, quality

    def generate(self, prompt, negative, refs, cancel=None):
        full = prompt + (f"\nAvoid: {negative}." if negative else "")
        auth = {"Authorization": f"Bearer {self._key}"}
        if refs:
            fields = {"model": self.model, "prompt": full, "size": "1536x1024", "n": "1",
                      "quality": self.quality}
            files = [("image[]", f"ref{i}.png", r, "image/png") for i, r in enumerate(refs[:4])]
            body, ctype = _multipart(fields, files)
            data = _http("POST", f"{self.base_url}/images/edits", headers={**auth, "Content-Type": ctype},
                         body=body, timeout=TIMEOUT_S, cancel=cancel)
        else:
            body = json.dumps({"model": self.model, "prompt": full, "size": "1536x1024", "n": 1,
                               "quality": self.quality}).encode()
            data = _http("POST", f"{self.base_url}/images/generations",
                         headers={**auth, "Content-Type": "application/json"}, body=body,
                         timeout=TIMEOUT_S, cancel=cancel)
        try:
            item = data["data"][0]
        except (KeyError, IndexError, TypeError) as e:
            raise ProviderError("The provider response contained no image.") from e
        if item.get("b64_json"):
            return base64.b64decode(item["b64_json"])
        raise ProviderError("The provider returned an image URL instead of image data; "
                            "set a model that returns base64 (e.g. gpt-image-1).")


class SDWebUI(ImageProvider):
    def __init__(self, base_url: str, steps: int):
        super().__init__("sdwebui", "Stable Diffusion WebUI", "your loaded checkpoint", base_url.rstrip("/"),
                         not _is_local(base_url), {"generate", "reference"},
                         "Runs on your own GPU; free and private when local.")
        self.steps = steps

    def generate(self, prompt, negative, refs, cancel=None):
        payload = {"prompt": prompt, "negative_prompt": negative, "width": 1344, "height": 768,
                   "steps": self.steps, "cfg_scale": 6, "batch_size": 1}
        path = "/sdapi/v1/txt2img"
        if refs:
            payload.update(init_images=[base64.b64encode(refs[0]).decode()], denoising_strength=0.62)
            path = "/sdapi/v1/img2img"
        data = _http("POST", self.base_url + path, headers={"Content-Type": "application/json"},
                     body=json.dumps(payload).encode(), timeout=TIMEOUT_S * 2, cancel=cancel)
        imgs = data.get("images") or []
        if not imgs:
            raise ProviderError("Stable Diffusion returned no image.")
        b64 = imgs[0].split(",", 1)[-1]
        return base64.b64decode(b64)


def image_provider() -> Optional[ImageProvider]:
    """Free/local first: Stable Diffusion WebUI is used automatically when its URL is
    set. The paid OpenAI provider is only used when explicitly chosen."""
    choice = os.environ.get("CLIPFORGE_IMAGE_PROVIDER", "auto").lower()
    sd = os.environ.get("CLIPFORGE_SDWEBUI_URL", "")
    if choice == "off":
        return None
    if choice in ("auto", "sdwebui") and sd:
        return SDWebUI(sd, int(os.environ.get("CLIPFORGE_SDWEBUI_STEPS", "28")))
    if choice == "openai":
        key = os.environ.get("OPENAI_API_KEY", "")
        if not key:
            return None
        return OpenAIImages(key, os.environ.get("CLIPFORGE_OPENAI_BASE_URL", "https://api.openai.com/v1"),
                            os.environ.get("CLIPFORGE_OPENAI_IMAGE_MODEL", "gpt-image-1"),
                            os.environ.get("CLIPFORGE_OPENAI_IMAGE_QUALITY", "medium"))
    return None


# ---------------------------------------------------------------- text model
@dataclass
class TextModel:
    base_url: str
    model: str
    key: str
    vision: bool

    @property
    def external(self) -> bool:
        return not _is_local(self.base_url)

    def info(self) -> dict:
        return {"model": self.model, "external": self.external, "vision": self.vision,
                "tested_against_real_service": False}

    def chat_json(self, system: str, user: str, images: Optional[list[bytes]] = None,
                  cancel: Optional[threading.Event] = None) -> dict:
        content: list | str = user
        if images:
            if not self.vision:
                raise ProviderError("This text model isn't configured for images (CLIPFORGE_LLM_VISION=1).")
            content = [{"type": "text", "text": user}] + [
                {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(i).decode()}}
                for i in images[:6]]
        body = {"model": self.model, "temperature": 0.8, "response_format": {"type": "json_object"},
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": content}]}
        headers = {"Content-Type": "application/json"}
        if self.key:
            headers["Authorization"] = f"Bearer {self.key}"
        data = _http("POST", f"{self.base_url.rstrip('/')}/chat/completions", headers=headers,
                     body=json.dumps(body).encode(), timeout=TIMEOUT_S, cancel=cancel)
        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as e:
            raise ProviderError("The text model returned no message.") from e
        m = re.search(r"\{.*\}", text or "", re.S)
        if not m:
            raise ProviderError("The text model didn't return JSON.")
        try:
            return json.loads(m.group(0))
        except ValueError as e:
            raise ProviderError("The text model returned invalid JSON.") from e


def text_model() -> Optional[TextModel]:
    """Optional. Uses CLIPFORGE_LLM_BASE_URL (e.g. a free local Ollama server).
    A paid API is only used if you point the base URL at one and give a key."""
    if os.environ.get("CLIPFORGE_LLM", "auto").lower() == "off":
        return None
    base = os.environ.get("CLIPFORGE_LLM_BASE_URL", "")
    if not base:
        return None
    return TextModel(base, os.environ.get("CLIPFORGE_LLM_MODEL", "llama3.1"),
                     os.environ.get("CLIPFORGE_LLM_API_KEY", ""),
                     os.environ.get("CLIPFORGE_LLM_VISION", "0") == "1")


SETUP_HELP = {
    "sdwebui": "Free: install Stable Diffusion WebUI Forge (needs an NVIDIA GPU, ~6-8 GB VRAM recommended), "
               "start it with the --api flag, then start ClipForge with CLIPFORGE_SDWEBUI_URL=http://127.0.0.1:7860.",
    "llm": "Optional and free: install Ollama, run `ollama pull llama3.1`, then start ClipForge with "
           "CLIPFORGE_LLM_BASE_URL=http://127.0.0.1:11434/v1.",
    "openai": "Optional, paid: CLIPFORGE_IMAGE_PROVIDER=openai and OPENAI_API_KEY=... (billed per image by OpenAI).",
}
