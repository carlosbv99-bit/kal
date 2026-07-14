"""
Tests de que el frontend estático se sirve SIN caché
(agent_core/orchestrator.py) — bug real encontrado en uso: un
`index.html` viejo cacheado por el navegador, servido junto con un
`app.js` ya actualizado (ese sí sin caché desde antes), rompía en
silencio porque el JS nuevo esperaba elementos que el HTML viejo no
tenía. `style.css`/`app.js` ya tenían esta protección; `index.html`
no la tenía — se agregó acá.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from agent_core.orchestrator import app

client = TestClient(app)


def test_index_html_is_served_without_cache():
    response = client.get("/")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert "text/html" in response.headers["content-type"]


def test_style_css_is_served_without_cache():
    response = client.get("/style.css")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"


def test_app_js_is_served_without_cache():
    response = client.get("/app.js")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
