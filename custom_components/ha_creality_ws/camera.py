from __future__ import annotations

import asyncio
from typing import Optional
import base64
import json

from aiohttp import ClientError, web
try:
    from homeassistant.components.camera import Camera, StreamType  # type: ignore[attr-defined]
except Exception:  # compatibility with older cores
    from homeassistant.components.camera import Camera  # type: ignore[assignment]
    StreamType = None  # type: ignore[assignment]
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    MJPEG_URL_TEMPLATE,
    DOMAIN,
    WEBRTC_URL_TEMPLATE,
)
from .entity import KEntity


class _BaseCamera(KEntity, Camera):
    """Common camera helpers (tiny JPEG fallback)."""

    # tiny 1x1 white JPEG as last-resort fallback (valid JFIF)
    _TINY_JPEG = (
        b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00H\x00H\x00\x00"
        b"\xff\xdb\x00C\x00" + b"\x08" * 64 +
        b"\xff\xc0\x00\x11\x08\x00\x01\x00\x01\x03\x01\x11\x00\x02\x11\x01\x03\x11\x01"
        b"\xff\xda\x00\x0c\x03\x01\x00\x02\x11\x03\x11\x00?\x00\xd2\xcf \xff\xd9"
    )

    def __init__(self, coordinator, name: str, unique_suffix: str) -> None:
        KEntity.__init__(self, coordinator, name, unique_suffix)
        Camera.__init__(self)
        self._last_frame: bytes | None = None

    async def _fallback_image(self) -> bytes:
        return self._last_frame or self._TINY_JPEG


class CrealityMjpegCamera(_BaseCamera):
    """MJPEG proxy camera attached to the printer device."""

    def __init__(self, coordinator, url: str) -> None:
        super().__init__(coordinator, "Printer Camera", "camera")
        self._url = url

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

        if frame is None:
            frame = await self._fallback_image()
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
            pass
        finally:
            await upstream.release()
        return resp


class CrealityWebRTCCamera(_BaseCamera):
    """Lightweight WebRTC camera that exposes signaling URL via attributes.

    Note: Home Assistant core camera entity doesn’t natively render WebRTC.
    Users typically use `webrtc-card` or `advanced-camera-card` with `webrtc:` URLs
    provided by go2rtc. We surface the correct URL so UI cards can bind.
    """

    def __init__(self, coordinator, signaling_url: str) -> None:
        super().__init__(coordinator, "Printer Camera", "camera")
        self._signaling_url = signaling_url
        # Hint HA frontend about type when available
        if StreamType is not None:
            try:
                self._attr_frontend_stream_type = StreamType.WEB_RTC  # type: ignore[attr-defined]
            except Exception:
                pass
        self._last_error: str | None = None

    async def async_camera_image(
        self,
        width: Optional[int] = None,
        height: Optional[int] = None,
    ) -> bytes | None:
        # Some HA surfaces call this for thumbnails; WebRTC has no snapshot.
        # Return last-good or tiny placeholder.
        return await self._fallback_image()

    @property
    def extra_state_attributes(self) -> dict:
        # Provide a ready-to-use webrtc-card URL matching existing community setups
        # Example: webrtc:http://<host>:8000/call/webrtc_local#format=creality
        attrs = {
            "webrtc_url": f"webrtc:{self._signaling_url}#format=creality",
            "signaling_url": self._signaling_url,
        }
        if self._last_error:
            attrs["error"] = self._last_error
        return attrs

    async def async_handle_web_rtc_offer(self, offer_sdp: str) -> str | None:  # type: ignore[override]
        """Forward HA's WebRTC SDP offer to the printer and return the SDP answer.

        Creality's endpoint expects a base64-encoded JSON string with fields {type:"offer", sdp:"..."}.
        It responds with base64 of the same structure containing the answer SDP.
        """
        # Build base64(JSON({type, sdp})) body
        obj = {"type": "offer", "sdp": offer_sdp}
        body_b64 = base64.b64encode(json.dumps(obj).encode("utf-8")).decode("ascii")

        session = async_get_clientsession(self.hass)
        try:
            async with session.post(
                self._signaling_url,
                data=body_b64,
                headers={"Content-Type": "plain/text"},
                timeout=10,
            ) as resp:
                if resp.status != 200:
                    # Return None to let frontend handle error state
                    self._last_error = f"signaling HTTP {resp.status}"
                    return None
                raw = await resp.read()
        except Exception as exc:
            self._last_error = f"signaling error: {exc}"
            return None

        # Decode base64 -> JSON -> extract answer SDP
        try:
            decoded = base64.b64decode(raw)
            payload = json.loads(decoded.decode("utf-8", "ignore"))
            return payload.get("sdp")
        except Exception as exc:
            self._last_error = f"invalid answer: {exc}"
            return None


async def _probe_webrtc_signaling(hass: HomeAssistant, url: str, timeout: float = 1.5) -> bool:
    """Probe the Creality WebRTC signaling endpoint with a cheap HEAD/GET.

    Printers typically answer on /call/webrtc_local even without a full offer body.
    We treat any 200-405 (method not allowed) as presence; 404/connection errors -> absent.
    """
    session = async_get_clientsession(hass)
    try:
        # First try HEAD (cheap). If not supported, fall back to GET
        async with session.head(url, timeout=timeout) as resp:
            if resp.status in (200, 204, 405):
                return True
    except Exception:
        pass
    try:
        async with session.get(url, timeout=timeout) as resp:
            if resp.status in (200, 204, 405):
                return True
    except Exception:
        return False
    return False


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities):
    coord = hass.data[DOMAIN][entry.entry_id]
    host = entry.data["host"]

    # Respect user-forced camera mode first
    cam_mode = entry.options.get("camera_mode")
    if cam_mode == "webrtc":
        async_add_entities([CrealityWebRTCCamera(coord, WEBRTC_URL_TEMPLATE.format(host=host))])
        return
    if cam_mode == "mjpeg":
        async_add_entities([CrealityMjpegCamera(coord, MJPEG_URL_TEMPLATE.format(host=host))])
        return

    # If printer is powered, wait briefly for first telemetry to identify model
    # This avoids misclassifying K2 as MJPEG when it's just booting.
    if not coord.power_is_off():
        try:
            await coord.wait_first_connect(timeout=2.0)
        except Exception:
            pass

    model = (coord.data or {}).get("model") or ""
    model_l = str(model).lower()

    # Prefer WebRTC for K2 family when indicated by model string
    webrtc_url = WEBRTC_URL_TEMPLATE.format(host=host)
    if "k2" in model_l:
        async_add_entities([CrealityWebRTCCamera(coord, webrtc_url)])
        return

    # Otherwise, detect WebRTC by probing the signaling endpoint quickly
    if await _probe_webrtc_signaling(hass, webrtc_url, timeout=1.5):
        async_add_entities([CrealityWebRTCCamera(coord, webrtc_url)])
        return

    # Fallback to MJPEG for K1 family
    mjpeg_url = MJPEG_URL_TEMPLATE.format(host=host)
    async_add_entities([CrealityMjpegCamera(coord, mjpeg_url)])
