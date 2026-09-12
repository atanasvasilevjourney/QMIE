"""Desk static files + Vercel hostname → Render API fallback."""
from __future__ import annotations

from pathlib import Path

from starlette.requests import Request

from desk_static import find_desk_dist, wants_html

ROOT = Path(__file__).resolve().parents[2]


def _request(accept: str) -> Request:
    return Request({
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "https",
        "path": "/",
        "raw_path": b"/",
        "query_string": b"",
        "headers": [(b"accept", accept.encode())],
        "client": ("127.0.0.1", 123),
        "server": ("test", 80),
    })


def test_wants_html_from_browser_accept():
    assert wants_html(_request("text/html,application/xhtml+xml;q=0.9"))
    assert not wants_html(_request("application/json"))
    assert not wants_html(_request("*/*"))


def test_find_desk_dist_sees_local_web_build_or_none():
    dist = find_desk_dist()
    local = ROOT / "web" / "dist" / "index.html"
    if local.is_file():
        assert dist is not None
        assert (dist / "index.html").is_file()
    else:
        assert dist in (None, Path("/app/desk"))


def test_dockerfile_builds_desk_stage():
    text = (ROOT / "docker" / "Dockerfile").read_text()
    assert "FROM node:22-alpine AS desk" in text
    assert "COPY --from=desk /src/dist /app/desk" in text


def test_bases_ts_vercel_host_falls_back_to_render():
    text = (ROOT / "web" / "src" / "api" / "bases.ts").read_text()
    assert "qmie.onrender.com" in text
    assert "vercel.app" in text
    assert "hostnameApiFallback" in text


def test_bases_ts_runtime_lists():
    import json
    import subprocess

    script = """
import { resolveApiBases, RENDER_API } from './src/api/bases.ts'
const cases = {
  local: resolveApiBases(undefined, 'localhost'),
  vercel: resolveApiBases(undefined, 'qmie.vercel.app'),
  preview: resolveApiBases(undefined, 'qmie-git-desk-api-404-a231.vercel.app'),
  custom: resolveApiBases(undefined, 'desk.example.com'),
  render: resolveApiBases(undefined, 'qmie.onrender.com'),
  envWins: resolveApiBases('https://custom.example', 'qmie.vercel.app'),
  envVercelIgnored: resolveApiBases('https://qmie.vercel.app', 'qmie.vercel.app'),
  renderApi: RENDER_API,
}
console.log(JSON.stringify(cases))
"""
    proc = subprocess.run(
        ["node", "--experimental-strip-types", "--input-type=module", "-e", script],
        cwd=ROOT / "web",
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    cases = json.loads(proc.stdout)
    assert cases["local"][0] == "/qmie"
    assert cases["vercel"] == ["https://qmie.onrender.com"]
    assert cases["preview"] == ["https://qmie.onrender.com"]
    assert cases["custom"] == ["https://qmie.onrender.com"]
    assert cases["render"] == [""]
    assert cases["envWins"] == ["https://custom.example", "https://qmie.onrender.com"]
    assert cases["envVercelIgnored"] == ["https://qmie.onrender.com"]
    assert cases["renderApi"] == "https://qmie.onrender.com"


def test_orbit_logo_pngs_cover_crypto_logo_ids():
    src = (ROOT / "web" / "src" / "cryptoLogos.ts").read_text()
    ids = []
    in_list = False
    for line in src.splitlines():
        if "export const CRYPTO_LOGOS" in line:
            in_list = True
            continue
        if in_list and line.strip().startswith("]"):
            break
        if in_list:
            token = line.strip().strip("',")
            if token:
                ids.append(token)
    assert "btc" in ids and "eth" in ids and "near" in ids
    missing = [i for i in ids if not (ROOT / "web" / "public" / "crypto" / f"{i}.png").is_file()]
    assert not missing, f"missing orbit logos: {missing}"
    assert "logoUrl" in src
    assert "import.meta.glob" in src


def test_vercel_json_proxies_health_and_radar_to_render():
    import json

    cfg = json.loads((ROOT / "vercel.json").read_text())
    sources = {row["source"]: row["destination"] for row in cfg["rewrites"]}
    assert sources["/health"] == "https://qmie.onrender.com/health"
    assert sources["/radar"] == "https://qmie.onrender.com/radar"
    assert sources["/(.*)"] == "/index.html"
