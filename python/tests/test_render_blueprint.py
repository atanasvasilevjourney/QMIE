"""Render hosts the FastAPI scanner as Docker; it must bind $PORT."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_docker_start_honors_port_env():
    text = (ROOT / "docker" / "start.sh").read_text()
    assert "PORT:-8080" in text
    assert "uvicorn main:app" in text


def test_dockerfile_uses_start_script():
    text = (ROOT / "docker" / "Dockerfile").read_text()
    assert "CMD [\"/app/start.sh\"]" in text
    assert "COPY docker/start.sh" in text
    assert "COPY --from=desk /src/dist /app/desk" in text


def test_render_blueprint_is_docker_web_not_static():
    text = (ROOT / "render.yaml").read_text()
    assert "type: web" in text
    assert "runtime: docker" in text
    assert "healthCheckPath: /health" in text
    assert "dockerfilePath: docker/Dockerfile" in text
    assert "numInstances: 1" in text
    assert "type: static" not in text
