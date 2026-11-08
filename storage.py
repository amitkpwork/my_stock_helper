"""Persistence + secrets.
If the secrets GIST_ID and GITHUB_TOKEN are set (hosted use), settings live in a private GitHub Gist so they
survive restarts. Otherwise plain local JSON files are used (running on your PC)."""
import json
import os
import urllib.request
from pathlib import Path

import streamlit as st

LOCAL = Path(__file__).parent


def secret(name: str, default=None):
    try:
        if name in st.secrets:
            return st.secrets[name]
    except Exception:
        pass
    return os.environ.get(name, default)


def _gist():
    gid, tok = secret("GIST_ID"), secret("GITHUB_TOKEN")
    return (str(gid), str(tok)) if gid and tok else None


def _call(method: str, url: str, token: str, body: dict | None = None) -> dict:
    req = urllib.request.Request(
        url, method=method, data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                 "User-Agent": "my_stock_helper", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r)


def load(name: str, default):
    g = _gist()
    try:
        if g:
            files = _call("GET", f"https://api.github.com/gists/{g[0]}", g[1])["files"]
            return json.loads(files[name]["content"]) if name in files else default
        p = LOCAL / name
        return json.loads(p.read_text()) if p.exists() else default
    except Exception:
        return default


def save(name: str, obj) -> bool:
    g = _gist()
    try:
        if g:
            _call("PATCH", f"https://api.github.com/gists/{g[0]}", g[1],
                  {"files": {name: {"content": json.dumps(obj, indent=1)}}})
        else:
            (LOCAL / name).write_text(json.dumps(obj))
        return True
    except Exception:
        return False
