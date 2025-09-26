from __future__ import annotations

import asyncio
from aiohttp import ClientError, web
from homeassistant.components.camera import Camera
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import MJPEG_URL_TEMPLATE, DOMAIN
from .entity import K1CEntity


class CrealityMjpegCamera(K1CEntity, Camera):
    """MJPEG proxy camera attached to the printer device."""

    def __init__(self, coordinator, url: str) -> None:
        K1CEntity.__init__(self, coordinator, "Printer Camera", "camera")
        Camera.__init__(self)
        self._url = url

    async def async_camera_image(self, width: int | None = None, height: int | None = None) -> bytes | None:
        # No separate snapshot endpoint; stream-only.
        return None

    async def handle_async_mjpeg_stream(self, request):
        """Open upstream MJPEG and relay bytes to the client."""
        session = async_get_clientsession(self.hass)
        try:
            upstream = await session.get(self._url, timeout=None)
        except ClientError:
            return web.Response(status=502, text="Upstream camera connection failed")

        if upstream.status != 200:
            txt = await upstream.text(errors="ignore")
            return web.Response(status=upstream.status, text=txt)

        ctype = upstream.headers.get("Content-Type", "multipart/x-mixed-replace;boundary=frame")
        resp = web.StreamResponse(status=200, headers={"Content-Type": ctype})
        await resp.prepare(request)

        try:
            async for chunk in upstream.content.iter_chunked(8192):
                await resp.write(chunk)
        except (ClientError, ConnectionResetError, asyncio.CancelledError):
            pass
        finally:
            await upstream.release()
        return resp


async def async_setup_entry(hass, entry, async_add_entities):
    coord = hass.data[DOMAIN][entry.entry_id]
    host = entry.data["host"]
    url = MJPEG_URL_TEMPLATE.format(host=host)
    async_add_entities([CrealityMjpegCamera(coord, url)])
