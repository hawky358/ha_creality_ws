from __future__ import annotations

import logging
from typing import Any

from aiohttp import ClientSession, ClientResponseError, web
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

_LOGGER = logging.getLogger(__name__)


class WebrtcProxy:
    """Simple proxy to forward Creality-style base64 offer from browser to printer signaling URL.

    The browser posts to HA over HTTPS, HA forwards the request to the insecure
    signaling URL (HTTP) and returns the response. This avoids mixed-content
    blocking in the browser during local testing.
    """

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._registered = False

    async def async_register(self) -> None:
        if self._registered:
            return

        @callback
        def _handle_request(request):
            # aiohttp.web.Request forwarded via hass.http
            return self.hass.async_create_task(self._handle_proxy(request))

        # Mount at a stable path under integration namespace
        self.hass.http.register_view(_ProxyView(self))
        self._registered = True
        _LOGGER.debug("Webrtc proxy view registered at /api/ha_creality_ws/webrtc_proxy")

    async def async_unregister(self) -> None:
        # Home Assistant does not offer an official unregister for views; best-effort
        # No-op: views are lightweight for testing. Keep for symmetry.
        self._registered = False

    async def _handle_proxy(self, request) -> Any:
        # Extract entity parameter and body
        hass = self.hass
        params = request.rel_url.query
        entity = params.get("entity")
        if not entity:
            return web.Response(status=400, text="Missing entity query param")

        # Find camera entity state to get signaling_url
        state = hass.states.get(entity)
        if state is None:
            return web.Response(status=404, text="Entity not found")

        signaling_url = state.attributes.get("signaling_url")
        if not signaling_url:
            return web.Response(status=400, text="Entity has no signaling_url")

        # Log incoming request metadata to help debug HEAD vs POST behavior
        try:
            _LOGGER.debug(
                "ha_creality_ws: proxy received request method=%s remote=%s path=%s headers=%s",
                request.method,
                request.remote,
                request.path,
                {k: v for k, v in request.headers.items() if k.lower() in ("content-type", "content-length", "user-agent")},
            )
        except Exception:
            pass

        body = await request.read()
        _LOGGER.warning("ha_creality_ws: proxying WebRTC offer len=%d to %s (method=%s)", len(body or b""), signaling_url, request.method)
        # Forward to signaling_url using HA's client session
        session: ClientSession = async_get_clientsession(hass)
        ctype = request.headers.get("Content-Type", "application/octet-stream")
        headers = {"Content-Type": ctype}
        # Only disable SSL verification for plain http; use True (default verify) for https.
        ssl_param: bool = False if signaling_url.lower().startswith("http://") else True
        try:
            async with session.post(signaling_url, data=body, headers=headers, ssl=ssl_param) as resp:
                data = await resp.read()
                _LOGGER.warning("ha_creality_ws: proxy upstream status=%s, resp_len=%d, ctype=%s", resp.status, len(data or b""), resp.content_type)
                return web.Response(status=resp.status, body=data, content_type=resp.content_type)
        except ClientResponseError as exc:
            _LOGGER.exception("Error forwarding to signaling_url %s: %s", signaling_url, exc)
            return web.Response(status=502, text=str(exc))
        except Exception as exc:  # pragma: no cover - network errors
            _LOGGER.exception("Unexpected error forwarding WebRTC proxy: %s", exc)
            return web.Response(status=500, text=str(exc))


from homeassistant.components.http import HomeAssistantView


class _ProxyView(HomeAssistantView):
    url = "/api/ha_creality_ws/webrtc_proxy"
    name = "api:ha_creality_ws:webrtc_proxy"
    requires_auth = True

    def __init__(self, proxy: WebrtcProxy) -> None:
        super().__init__()
        self._proxy = proxy

    async def post(self, request):
        # delegate to proxy handler
        return await self._proxy._handle_proxy(request)
