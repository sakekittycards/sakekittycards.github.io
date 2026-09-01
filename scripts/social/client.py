# -*- coding: utf-8 -*-
"""Thin client for the sakekitty-social worker.

The admin token is read from a file, never a command-line argument — an argument
lands in shell history and in the process table.

Resolution order:
  1. $SK_SOCIAL_TOKEN
  2. ~/.claude/sk_social_admin_token.txt
  3. ~/.claude/sk_admin_token.txt        (shared with the square worker)
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

DEFAULT_BASE = "https://sakekitty-social.nwilliams23999.workers.dev"
USER_AGENT = "sakekitty-social-agent/1.0 (+https://sakekittycards.com)"

TOKEN_FILES = [
    os.path.expanduser("~/.claude/sk_social_admin_token.txt"),
    os.path.expanduser("~/.claude/sk_admin_token.txt"),
]


class SocialError(RuntimeError):
    def __init__(self, message, status=None, body=None):
        super().__init__(message)
        self.status = status
        self.body = body


def _token() -> str:
    tok = os.environ.get("SK_SOCIAL_TOKEN", "").strip()
    if tok:
        return tok
    for path in TOKEN_FILES:
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                tok = fh.read().strip()
            if tok:
                return tok
    raise SocialError(
        "no admin token. Set SK_SOCIAL_TOKEN, or put the worker's ADMIN_TOKEN in "
        f"{TOKEN_FILES[0]}"
    )


class Client:
    def __init__(self, base: str | None = None, token: str | None = None):
        self.base = (base or os.environ.get("SK_SOCIAL_BASE") or DEFAULT_BASE).rstrip("/")
        self._token = token or _token()

    def _call(self, method: str, path: str, payload=None, retries: int = 2):
        url = self.base + path
        data = json.dumps(payload).encode() if payload is not None else None
        last = None
        for attempt in range(retries + 1):
            req = urllib.request.Request(url, data=data, method=method)
            req.add_header("X-Sake-Admin-Token", self._token)
            # Identify ourselves. Cloudflare's edge answers urllib's default
            # User-Agent with a 1010 browser-signature block, which surfaces as a
            # baffling 403 from our own worker. The repo already hit this with
            # tcgcsv; same fix, same reason.
            req.add_header("User-Agent", USER_AGENT)
            req.add_header("Accept", "application/json")
            if data:
                req.add_header("Content-Type", "application/json")
            try:
                with urllib.request.urlopen(req, timeout=120) as res:
                    return json.loads(res.read().decode() or "{}")
            except urllib.error.HTTPError as e:
                body = e.read().decode(errors="replace")
                # 4xx is our mistake and will not fix itself; only retry 5xx.
                if e.code < 500:
                    try:
                        msg = json.loads(body).get("error", body)
                    except Exception:
                        msg = body
                    raise SocialError(f"{method} {path} -> {e.code}: {msg}", e.code, body)
                last = SocialError(f"{method} {path} -> {e.code}", e.code, body)
            except urllib.error.URLError as e:
                last = SocialError(f"{method} {path} -> {e.reason}")
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
        raise last

    def get(self, path, **params):
        if params:
            from urllib.parse import urlencode
            clean = {k: v for k, v in params.items() if v is not None}
            if clean:
                path += ("&" if "?" in path else "?") + urlencode(clean)
        return self._call("GET", path)

    def post(self, path, payload=None):
        return self._call("POST", path, payload if payload is not None else {})

    # ── Convenience wrappers ────────────────────────────────────────────────
    def upload_image(self, png_bytes: bytes, *, width, height, template, **extra):
        import base64
        return self.post("/media/upload", {
            "data_b64": base64.b64encode(png_bytes).decode(),
            "kind": "image", "content_type": "image/jpeg",
            "width": width, "height": height, "template": template, **extra,
        })["media"]

    def upload_video(self, path: str, **extra):
        import base64
        with open(path, "rb") as fh:
            raw = fh.read()
        return self.post("/media/upload", {
            "data_b64": base64.b64encode(raw).decode(),
            "kind": "video", "content_type": "video/mp4",
            "original_name": os.path.basename(path), **extra,
        })["media"]

    def health(self):
        req = urllib.request.Request(self.base + "/health")
        req.add_header("User-Agent", USER_AGENT)
        with urllib.request.urlopen(req, timeout=30) as res:
            return json.loads(res.read().decode())
