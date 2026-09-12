"""HTTP basic auth + 404 template rendering.

BasicAuthMiddleware gates every request in production (APP_ENV=production,
incl. static); the WWW-Authenticate header is sent only when credentials are
absent. /health is exempt — a health check behind auth is useless to
Railway's uptime checks.

Production without BASIC_AUTH_USER/BASIC_AUTH_PASS is a configuration error:
raising at startup beats silently running without the gate.

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
from django.utils.cache import patch_cache_control

from . import views


class CacheControlMiddleware:
    """Set Cache-Control: private, max-age=300 on GET responses.

    private — browsers may cache; shared proxies must not.
    max-age=300 — serve from cache for 5 minutes without hitting the server;
    after expiry the browser revalidates via If-None-Match and ConditionalGetMiddleware
    returns 304 Not Modified when content is unchanged.
    Only applied to 200/304 GET responses; errors and non-GET methods are left alone.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if request.method == "GET" and response.status_code in (200, 304):
            patch_cache_control(response, private=True, max_age=300)
        return response


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
