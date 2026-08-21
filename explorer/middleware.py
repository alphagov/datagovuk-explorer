"""HTTP basic auth + 404 template rendering.

BasicAuthMiddleware gates every request in production (APP_ENV=production,
incl. static); the WWW-Authenticate header is sent only when credentials are
absent. /health is exempt — a health check behind auth is useless to
Railway's uptime checks.

Production without BASIC_AUTH_USER/BASIC_AUTH_PASS is a configuration error:
raising at startup beats silently running without the gate (the old
behaviour — `enabled` required both creds, so a missing one turned auth off).

Dev-only note: whitenoise.runserver_nostatic (see config/settings.py) makes
WhiteNoise serve /static/ through the middleware chain locally too, so the
gate applies to static in both environments — unlike stock runserver, which
serves static before middleware when DEBUG=True.
"""

import base64
import binascii
import os

from django.core.exceptions import ImproperlyConfigured
from django.http import Http404, HttpResponse

from . import views


class NotFoundMiddleware:
    """Render templates/404.html for every Http404, in both DEBUG modes.

    Django 6 shows its technical debug 404 page whenever DEBUG=True and a
    view raises Http404 — the custom handler404 only runs with DEBUG=False.
    This middleware restores the 404.html rendering in every environment:
    process_exception runs before Django's exception fallback, and every
    404 in this app originates in a view (page views raise Http404; the
    catch-all 404 view is reached for unrouted paths and missing static
    files), so nothing escapes it.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        if isinstance(exception, Http404):
            return views.not_found(request, exception)
        return None


class BasicAuthMiddleware:
    """HTTP basic auth gate for production.

    All three env vars (APP_ENV, BASIC_AUTH_USER, BASIC_AUTH_PASS) are read
    at instantiation — i.e. once per process at startup, when Django builds
    the middleware chain — so a running process never picks up mid-flight
    env changes (that's intended; changing auth requires a redeploy).
    """

    def __init__(self, get_response):
        self.get_response = get_response
        self.auth_user = os.getenv("BASIC_AUTH_USER")
        self.auth_pass = os.getenv("BASIC_AUTH_PASS")
        self.is_production = os.getenv("APP_ENV") == "production"
        if self.is_production and (not self.auth_user or not self.auth_pass):
            raise ImproperlyConfigured(
                "APP_ENV=production requires BASIC_AUTH_USER and BASIC_AUTH_PASS "
                "(a deployment without them would silently run with no auth gate)",
            )
        self.enabled = self.is_production

    def __call__(self, request):
        if not self.enabled:
            return self.get_response(request)
        # /health must stay reachable without credentials — Railway probes it
        # to decide the deployment is up (and auth creds would make any
        # uptime/alerting tooling brittle).
        if request.path == "/health":
            return self.get_response(request)

        auth = request.headers.get("authorization")
        if not auth or not auth.startswith("Basic "):
            return HttpResponse(
                "Authentication required",
                status=401,
                headers={"WWW-Authenticate": 'Basic realm="data.gov.uk Explorer"'},
            )
        try:
            creds = base64.b64decode(auth[6:]).decode()
        except (binascii.Error, UnicodeDecodeError):
            return HttpResponse("Invalid credentials", status=401)
        user, _, pass_ = creds.partition(":")
        if user != self.auth_user or pass_ != self.auth_pass:
            return HttpResponse("Invalid credentials", status=401)
        return self.get_response(request)
