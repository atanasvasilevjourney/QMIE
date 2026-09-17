"""Vercel hosts the Vite desk only. Guard the output path so a root 404 cannot return."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_vercel_json_builds_web_dist():
    cfg = json.loads((ROOT / "vercel.json").read_text())
    assert cfg["outputDirectory"] == "web/dist"
    assert "npm --prefix web" in cfg["installCommand"]
    assert "npm --prefix web run build" in cfg["buildCommand"]
    assert cfg.get("framework") is None
    assert any(r.get("destination") == "/index.html" for r in cfg.get("rewrites", []))


def test_web_vercel_json_is_spa_rewrites_only():
    """Used when the dashboard Root Directory is `web` (paths are relative to web/)."""
    cfg = json.loads((ROOT / "web" / "vercel.json").read_text())
    assert "outputDirectory" not in cfg
    assert any(r.get("destination") == "/index.html" for r in cfg.get("rewrites", []))


def test_root_package_json_delegates_build_to_web():
    cfg = json.loads((ROOT / "package.json").read_text())
    assert "web" in cfg["scripts"]["build"]


def test_web_env_example_documents_api_origin():
    text = (ROOT / "web" / ".env.example").read_text()
    assert "VITE_QMIE_API=" in text
