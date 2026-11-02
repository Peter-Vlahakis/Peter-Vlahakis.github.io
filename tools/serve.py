#!/usr/bin/env python3
"""Local preview server that behaves like GitHub Pages where it matters.

    python tools/serve.py [--port 8000]      then open http://localhost:8000/

The port comes from --port, else the PORT environment variable, else 8000.

Differences from `python -m http.server`:
  * honours HTTP Range requests (video seeking and looping in Safari need them);
  * paths are case-sensitive, as on GitHub Pages (Windows would otherwise hide a wrong-case link);
  * unknown paths get 404.html; nothing is cached, so edits show on reload.

Standard library only. It always serves the repo root, whatever the current directory.
"""
from __future__ import annotations

import argparse
import mimetypes
import os
import re
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

SITE = Path(__file__).resolve().parent.parent
RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)$")
HIDDEN = {".git", ".venv", ".claude", "__pycache__", "INSTRUCTIONS.md"}  # never part of the published site
TYPES = {
    ".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8", ".js": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8", ".svg": "image/svg+xml", ".webp": "image/webp", ".jpg": "image/jpeg",
    ".png": "image/png", ".mp4": "video/mp4", ".woff2": "font/woff2", ".pdf": "application/pdf",
    ".glb": "model/gltf-binary", ".txt": "text/plain; charset=utf-8", ".md": "text/markdown; charset=utf-8",
}


def resolve(url_path: str) -> Path | None:
    """Map a URL path to a file under SITE, matching every segment's case exactly."""
    parts = [p for p in unquote(urlsplit(url_path).path).split("/") if p]
    cur = SITE
    for part in parts:
        if part in (".", "..") or part in HIDDEN or not cur.is_dir() or part not in os.listdir(cur):
            return None
        cur = cur / part
    if cur.is_dir():
        cur = cur / "index.html"
    return cur if cur.is_file() else None


class Handler(SimpleHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        self.respond(body=True)

    def do_HEAD(self) -> None:
        self.respond(body=False)

    def respond(self, body: bool) -> None:
        path, status = resolve(self.path), HTTPStatus.OK
        if path is None:
            path, status = SITE / "404.html", HTTPStatus.NOT_FOUND
            if not path.is_file():
                self.send_error(HTTPStatus.NOT_FOUND)
                return
        size = path.stat().st_size
        start, end = 0, size - 1
        match = RANGE_RE.match(self.headers.get("Range", "").strip()) if status == HTTPStatus.OK else None
        if match and (match.group(1) or match.group(2)):
            first, last = match.groups()
            if first:
                start, end = int(first), min(int(last), size - 1) if last else size - 1
            else:  # suffix range: the final N bytes
                start = max(size - int(last), 0)
            if start > end or start >= size:
                self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            status = HTTPStatus.PARTIAL_CONTENT

        self.send_response(status)
        ctype = TYPES.get(path.suffix.lower()) or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "no-store")
        if status == HTTPStatus.PARTIAL_CONTENT:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        if not body:
            return
        with path.open("rb") as fh:
            fh.seek(start)
            remaining = end - start + 1
            try:
                while remaining > 0:
                    chunk = fh.read(min(64 * 1024, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
            except (BrokenPipeError, ConnectionError):
                pass  # the browser dropped the connection (normal for video)

    def log_message(self, fmt: str, *args) -> None:
        if not getattr(self.server, "quiet", False):
            super().log_message(fmt, *args)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8000)),
                    help="default: the PORT environment variable, else 8000")
    ap.add_argument("--bind", default="127.0.0.1")
    ap.add_argument("--quiet", action="store_true", help="do not log each request")
    args = ap.parse_args()
    server = ThreadingHTTPServer((args.bind, args.port), Handler)
    server.quiet = args.quiet
    print(f"Serving {SITE} at http://localhost:{args.port}/  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
