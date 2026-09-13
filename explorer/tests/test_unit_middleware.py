"""Unit tests for health, basic auth, and custom 404 rendering.

These need no database (health returns a bare response; the 404 template has
no data) so they never skip. The page-render route smoke lives in
``test_integration_routes.py``.
"""

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.http import HttpRequest, HttpResponse

import explorer.middleware as mw


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.content == b"ok"


def test_health_exempt_from_basic_auth(monkeypatch):
    """/health must stay reachable without credentials when the gate is on
    (Railway probes it; auth there would make uptime tooling brittle)."""
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("BASIC_AUTH_USER", "user")
    monkeypatch.setenv("BASIC_AUTH_PASS", "pass")

    gate = mw.BasicAuthMiddleware(lambda request: HttpResponse("ok"))
    assert gate.enabled

    request = HttpRequest()
    request.path = "/health"
    assert gate(request).status_code == 200

    request.path = "/datasets"
    assert gate(request).status_code == 401


def test_basic_auth_off_in_development(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("BASIC_AUTH_USER", "user")
    monkeypatch.setenv("BASIC_AUTH_PASS", "pass")
    assert not mw.BasicAuthMiddleware(lambda request: HttpResponse("ok")).enabled


def test_production_requires_creds(monkeypatch):
    """Production without credentials is a startup error — never run
    unauthenticated."""
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("BASIC_AUTH_USER", raising=False)
    monkeypatch.delenv("BASIC_AUTH_PASS", raising=False)
    with pytest.raises(ImproperlyConfigured):
        mw.BasicAuthMiddleware(lambda request: HttpResponse("ok"))


def test_unknown_route_renders_404(client):
    """Unrouted paths render 404.html, not Django's technical 404 page
    (assert template-only markup, not the storage-dependent static URL)."""
    response = client.get("/no-such-page")
    assert response.status_code == 404
    html = response.content.decode()
    assert "404 — Page not found" in html
    assert 'href="/"' in html  # the 404 template's back-home link
