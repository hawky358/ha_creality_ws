from __future__ import annotations

import asyncio
from typing import Optional

from aiohttp import ClientError, web
from homeassistant.components.camera import Camera
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import MJPEG_URL_TEMPLATE, DOMAIN
from .entity import KEntity


class CrealityMjpegCamera(KEntity, Camera):
    """MJPEG proxy camera attached to the printer device."""

    # tiny 1x1 white JPEG as last-resort fallback (valid JFIF)
    _TINY_JPEG = (
        b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00H\x00H\x00\x00"
        b"\xff\xdb\x00C\x00" + b"\x08" * 64 +
        b"\xff\xc0\x00\x11\x08\x00\x01\x00\x01\x03\x01\x11\x00\x02\x11\x01\x03\x11\x01"
        b"\xff\xda\x00\x0c\x03\x01\x00\x02\x11\x03\x11\x00?\x00\xd2\xcf \xff\xd9"
    )

    def __init__(self, coordinator, url: str) -> None:
        KEntity.__init__(self, coordinator, "Printer Camera", "camera")
        Camera.__init__(self)
        self._url = url
        self._last_frame: bytes | None = None

    async def _grab_snapshot_from_mjpeg(self, timeout: float = 5.0) -> bytes | None:
        """
        Open the MJPEG URL and return the first JPEG frame (bytes).
        Works even if there is no dedicated /snapshot endpoint.
        """
        session = async_get_clientsession(self.hass)
        try:
            async with session.get(self._url, timeout=timeout) as resp:
                if resp.status != 200:
                    return None
                buf = bytearray()
                in_frame = False
                async for chunk in resp.content.iter_chunked(8192):
                    if not in_frame:
                        i = chunk.find(b"\xff\xd8")  # SOI
                        if i != -1:
                            in_frame = True
                            buf.extend(chunk[i:])
                        continue
                    buf.extend(chunk)
                    # Search EOI near the end to avoid O(n^2)
                    tail_start = max(0, len(buf) - 8192)
                    j = buf.find(b"\xff\xd9", tail_start)  # EOI
                    if j != -1:
                        return bytes(buf[: j + 2])
        except (asyncio.CancelledError, ClientError, asyncio.TimeoutError):
            return None
        except Exception:
            return None
        return None

    async def async_camera_image(
        self,
        width: Optional[int] = None,
        height: Optional[int] = None,
    ) -> bytes | None:
        """
        Return a single JPEG frame. Never raise; never return invalid 0-sized data.
        We let HA do any scaling; treat 0/None as "no resize".
        """
        if not width or width <= 0:
            width = None
        if not height or height <= 0:
            height = None

        frame: bytes | None = None
        # Only try grabbing a fresh frame when the printer is powered
        if not self.coordinator.power_is_off():
            frame = await self._grab_snapshot_from_mjpeg(timeout=5.0)
            if frame:
                self._last_frame = frame

        # Fallback chain: cached last-good → tiny valid JPEG
        if frame is None:
            frame = self._last_frame or self._TINY_JPEG

        return frame

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
            # expected on dialog close; do not log an error and do not re-raise
            pass
        finally:
            await upstream.release()
        return resp


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities):
    coord = hass.data[DOMAIN][entry.entry_id]
    host = entry.data["host"]
    url = MJPEG_URL_TEMPLATE.format(host=host)
    async_add_entities([CrealityMjpegCamera(coord, url)])
