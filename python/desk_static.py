"""Serve the Vite desk when a built dist/ is present.

Docker copies `web/dist` to `/app/desk`. Locally, `web/dist` after
`npm run build` also works. Missing dist is not an error — `/` stays JSON.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse


def find_desk_dist() -> Path | None:
    here = Path(__file__).resolve().parent
    candidates = (
        Path("/app/desk"),
        here / "desk",
        here.parent / "web" / "dist",
    )
    for path in candidates:
        if (path / "index.html").is_file():
            return path
    return None


def wants_html(request: Request) -> bool:
    accept = request.headers.get("accept") or ""
    return "text/html" in accept


def desk_file(rel: str) -> FileResponse:
    dist = find_desk_dist()
    if dist is None:
        raise HTTPException(404, "desk_not_built")
    root = dist.resolve()
    target = (dist / rel).resolve()
    if not target.is_relative_to(root) or not target.is_file():
        raise HTTPException(404)
    media = "text/html" if target.suffix in {".html", ".htm"} else None
    return FileResponse(target, media_type=media)
