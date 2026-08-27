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


def test_web_env_example_documents_api_origin():
    text = (ROOT / "web" / ".env.example").read_text()
    assert "VITE_QMIE_API=" in text
