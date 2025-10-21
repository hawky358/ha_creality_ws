from __future__ import annotations

import asyncio
from typing import Optional
import base64
import json
import logging

from aiohttp import ClientError, web
try:
    from homeassistant.components.camera import Camera, StreamType, CameraEntityFeature  # type: ignore[attr-defined]
except Exception:  # compatibility with older cores
    from homeassistant.components.camera import Camera  # type: ignore[assignment]
    StreamType = None  # type: ignore[assignment]
    try:
        from homeassistant.components.camera import CameraEntityFeature  # type: ignore[misc]
    except Exception:  # very old cores
        CameraEntityFeature = None  # type: ignore[assignment]
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

FALLBACK_WEBRTC_BIT = 1 << 13  # align with HA's WEB_RTC flag in newer builds

from .const import (
    MJPEG_URL_TEMPLATE,
    DOMAIN,
    WEBRTC_URL_TEMPLATE,
)
from .entity import KEntity

_LOGGER = logging.getLogger(__name__)


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

    def _is_valid_jpeg(self, data: bytes) -> bool:
        if not data or len(data) < 20:
            return False
        return data.startswith(b"\xff\xd8") and data.endswith(b"\xff\xd9")

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
        except Exception:  # pragma: no cover - defensive
            _LOGGER.exception("ha_creality_ws: unexpected error grabbing MJPEG snapshot")
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
            try:
                frame = await self._grab_snapshot_from_mjpeg(timeout=5.0)
            except Exception:  # pragma: no cover - defensive
                _LOGGER.exception("ha_creality_ws: unexpected error while fetching MJPEG snapshot")
                frame = None
            if frame and self._is_valid_jpeg(frame):
                self._last_frame = frame
            elif frame:
                _LOGGER.debug("Dropping invalid MJPEG frame from upstream")

        if frame is None:
            frame = await self._fallback_image()
        else:
            if not self._is_valid_jpeg(frame):
                _LOGGER.debug("Upstream frame invalid, returning fallback image")
                frame = await self._fallback_image()
        return frame

    async def handle_async_mjpeg_stream(self, request):
        """Open upstream MJPEG and relay bytes to the client."""
        session = async_get_clientsession(self.hass)
        try:
            upstream = await session.get(self._url, timeout=None)
        except ClientError:
            _LOGGER.warning("ha_creality_ws: upstream MJPEG connection failed to %s", self._url)
            return web.Response(status=502, text="Upstream camera connection failed")
        except Exception:
            _LOGGER.exception("ha_creality_ws: unexpected error opening upstream MJPEG %s", self._url)
            return web.Response(status=502, text="Upstream camera error")

        try:
            if upstream.status != 200:
                txt = await upstream.text(errors="ignore")
                _LOGGER.warning("ha_creality_ws: upstream MJPEG returned status=%s text=%s", upstream.status, txt[:200])
                return web.Response(status=upstream.status, text=txt)

            ctype = upstream.headers.get("Content-Type", "multipart/x-mixed-replace;boundary=frame")
            resp = web.StreamResponse(status=200, headers={"Content-Type": ctype})
            await resp.prepare(request)

            try:
                async for chunk in upstream.content.iter_chunked(8192):
                    await resp.write(chunk)
            except (ClientError, ConnectionResetError, asyncio.CancelledError):
                pass
            except Exception:
                _LOGGER.exception("ha_creality_ws: error while streaming MJPEG from %s", self._url)
            finally:
                await upstream.release()
            return resp
        except Exception:
            _LOGGER.exception("ha_creality_ws: unexpected error handling MJPEG stream from %s", self._url)
            try:
                await upstream.release()
            except Exception:
                pass
            return web.Response(status=502, text="Upstream camera error")


class CrealityWebRTCCamera(_BaseCamera):
    """Lightweight WebRTC camera that exposes signaling URL via attributes.

    Note: Home Assistant core camera entity doesn’t natively render WebRTC.
    Users typically use `webrtc-card` or `advanced-camera-card` with `webrtc:` URLs
    provided by go2rtc. We surface the correct URL so UI cards can bind.
    """

    def __init__(self, coordinator, signaling_url: str, use_proxy: bool = False) -> None:
        super().__init__(coordinator, "Printer Camera", "camera")
        # Always keep the upstream device signaling URL separate
        self._upstream_signaling_url = signaling_url
        # Optional proxy path (computed in async_added_to_hass)
        self._proxy_signaling_url: str | None = None
        self._use_proxy = use_proxy
        # Hint HA frontend about type when available
        if StreamType is not None:
            try:
                self._attr_frontend_stream_type = StreamType.WEB_RTC  # type: ignore[attr-defined]
            except Exception:
                pass
        # Advertise streaming capability so HA frontend/cards attempt WebRTC
        self._feature_mask: int = 0
        if "CameraEntityFeature" in globals() and CameraEntityFeature is not None:  # type: ignore[name-defined]
            # Build a clear IntFlag including STREAM, WEB_RTC, and ON_DEMAND where available
            try:
                stream_flag = getattr(CameraEntityFeature, "STREAM")
            except Exception:
                stream_flag = CameraEntityFeature(1)
            try:
                webrtc_flag = getattr(CameraEntityFeature, "WEB_RTC")
            except Exception:
                webrtc_flag = CameraEntityFeature(FALLBACK_WEBRTC_BIT)
            try:
                ondemand_flag = getattr(CameraEntityFeature, "ON_DEMAND")
            except Exception:
                ondemand_flag = CameraEntityFeature(0)

            features_flag = stream_flag | webrtc_flag | ondemand_flag
            flag_details: dict[str, tuple[int | None, str]] = {}
            for attr in ("STREAM", "WEB_RTC", "ON_DEMAND"):
                value = getattr(CameraEntityFeature, attr, None)
                int_value: int | None
                try:
                    int_value = int(value) if value is not None else None
                except Exception:
                    int_value = None
                if isinstance(value, CameraEntityFeature):
                    features_flag |= value
                    flag_details[attr] = (int_value, repr(value))
                elif attr == "WEB_RTC":
                    fallback_flag = CameraEntityFeature(FALLBACK_WEBRTC_BIT)
                    features_flag |= fallback_flag
                    flag_details[attr] = (int(fallback_flag), repr(fallback_flag))
                else:
                    flag_details[attr] = (int_value, repr(value))

            if not features_flag:
                # ensure at least STREAM fallback bit is present
                try:
                    features_flag = CameraEntityFeature(getattr(CameraEntityFeature, "STREAM"))
                except Exception:
                    features_flag = CameraEntityFeature(0)

            try:
                _LOGGER.warning(
                    "ha_creality_ws: CameraEntityFeature flags=%s, combined=%r",
                    flag_details,
                    features_flag,
                )
            except Exception:
                pass

            self._feature_mask = int(features_flag)
            # Store the IntFlag instance so HA sees an iterable/flag object
            self._attr_supported_features = features_flag
        else:
            self._feature_mask = 1
            self._attr_supported_features = 1
        self._last_error: str | None = None
        # lightweight diagnostics to help validate end-to-end
        self._last_offer_len: int = 0
        self._last_answer_len: int = 0
        self._last_signaling_status: int | None = None

    async def async_added_to_hass(self) -> None:
        # If the integration option requested proxying, rewrite signaling_url
        # to point to HA's proxy endpoint so the browser posts to HA (HTTPS).
        await super().async_added_to_hass()
        if self._use_proxy:
            # Build a relative proxy path so the browser posts to HA (HTTPS), avoiding mixed-content
            self._proxy_signaling_url = f"/api/ha_creality_ws/webrtc_proxy?entity={self.entity_id}"
        # Log key configuration for troubleshooting
        try:
            sf = self.supported_features
            _LOGGER.warning(
                "ha_creality_ws: camera added: supported_features=%s (repr=%r type=%s) mask=%s, frontend_stream_type=%s, upstream_signaling=%s, proxy=%s",
                sf,
                repr(sf),
                type(sf),
                getattr(self, "_feature_mask", None),
                getattr(self, "_attr_frontend_stream_type", None),
                getattr(self, "_upstream_signaling_url", None),
                getattr(self, "_proxy_signaling_url", None),
            )
        except Exception:
            pass

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
        # Expose webrtc_url for frontend cards; if proxy is enabled and available, point there.
        target_for_frontend = self._proxy_signaling_url if (self._use_proxy and self._proxy_signaling_url) else self._upstream_signaling_url
        attrs = {
            "webrtc_url": f"webrtc:{target_for_frontend}#format=creality",
            # IMPORTANT: expose upstream signaling_url so the proxy can forward correctly
            "signaling_url": self._upstream_signaling_url,
            "webrtc_using_proxy": bool(self._use_proxy and self._proxy_signaling_url),
            "webrtc_offer_len": self._last_offer_len,
            "webrtc_answer_len": self._last_answer_len,
            "webrtc_signaling_status": self._last_signaling_status,
        }
        if self._last_error:
            attrs["error"] = self._last_error
        return attrs

    async def async_get_stream_source(self) -> str | None:  # type: ignore[override]
        """Return a frontend-usable stream source for this camera.

        We return the webrtc: URL (proxy if enabled) so other integrations that
        request a source (like the WebRTC helper or proxy) can obtain it. Note
        that Home Assistant's built-in play_stream service expects HLS/HTTP
        sources; this integration exposes WebRTC only, so recommend using a
        webrtc-capable card (webrtc-card) for playback.
        """
        target_for_frontend = self._proxy_signaling_url if (self._use_proxy and self._proxy_signaling_url) else self._upstream_signaling_url
        if not target_for_frontend:
            return None
        return f"webrtc:{target_for_frontend}#format=creality"

    async def stream_source(self) -> str | None:  # type: ignore[override]
        """Async stream source helper used by HA internals/tests.

        HA may call and await camera.stream_source(); provide an async function
        for compatibility.
        """
        try:
            target_for_frontend = self._proxy_signaling_url if (self._use_proxy and self._proxy_signaling_url) else self._upstream_signaling_url
            if not target_for_frontend:
                return None
            return f"webrtc:{target_for_frontend}#format=creality"
        except Exception:
            return None

    async def async_play_stream(self, media_player, format: str = "hls", **kwargs):  # type: ignore[override]
        """Handle play_stream service calls.

        Home Assistant's play_stream service is HLS-focused. Our camera is
        WebRTC-only, so we don't provide an HLS stream. Implement a defensive
        noop so calls don't raise 'does not support play stream service'.
        """
        _LOGGER.warning(
            "ha_creality_ws: play_stream requested for %s with format=%s - WebRTC-only; use a WebRTC-capable card",
            self.entity_id,
            format,
        )
        # Nothing to stream server-side; return None to indicate no stream was started
        return None

    @property
    def supported_features(self):  # type: ignore[override]
        mask = int(getattr(self, "_feature_mask", self._attr_supported_features))

        class _FeatureMask(int):
            def __contains__(self, item) -> bool:  # type: ignore[override]
                try:
                    return bool(int(self) & int(item))
                except Exception:
                    return False

        # Prefer returning a CameraEntityFeature IntFlag when the enum exists
        if "CameraEntityFeature" in globals() and CameraEntityFeature is not None:
            try:
                flag = CameraEntityFeature(mask)
                return flag
            except Exception:
                # Some HA builds may not accept construction; fall back to mask wrapper
                return _FeatureMask(mask)

        return _FeatureMask(mask)

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
            self._last_offer_len = len(offer_sdp or "")
            _LOGGER.warning("ha_creality_ws: async_handle_web_rtc_offer start len=%d upstream=%s", self._last_offer_len, self._upstream_signaling_url)
            async with session.post(
                self._upstream_signaling_url,
                data=body_b64,
                headers={"Content-Type": "text/plain"},
                timeout=10,
            ) as resp:
                self._last_signaling_status = int(resp.status)
                _LOGGER.warning("ha_creality_ws: signaling POST returned status=%s content-type=%s", resp.status, resp.content_type)
                if resp.status != 200:
                    # Return None to let frontend handle error state
                    self._last_error = f"signaling HTTP {resp.status}"
                    return None
                raw = await resp.read()
                self._last_answer_len = len(raw or b"")
                _LOGGER.warning("ha_creality_ws: signaling response length=%d", self._last_answer_len)
        except Exception as exc:
            _LOGGER.exception("Signaling error when POSTing to %s: %s", self._upstream_signaling_url, exc)
            self._last_error = f"signaling error: {exc}"
            return None

        # Decode base64 -> JSON -> extract answer SDP
        try:
            decoded = base64.b64decode(raw)
            payload = json.loads(decoded.decode("utf-8", "ignore"))
            _LOGGER.debug("Decoded signaling payload keys=%s", list(payload.keys()))
            sdp = payload.get("sdp")
            _LOGGER.debug("Answer SDP len=%d", len(sdp or ""))
            return sdp
        except Exception as exc:
            _LOGGER.exception("Invalid answer from signaling: %s", exc)
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
            _LOGGER.debug("ha_creality_ws: probe HEAD %s -> status=%s", url, resp.status)
            if resp.status in (200, 204, 405):
                return True
    except Exception:
        pass
    try:
        async with session.get(url, timeout=timeout) as resp:
            _LOGGER.debug("ha_creality_ws: probe GET %s -> status=%s", url, resp.status)
            if resp.status in (200, 204, 405):
                return True
    except Exception:
        return False
    return False


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities):
    coord = hass.data[DOMAIN][entry.entry_id]
    host = entry.data["host"]
    use_proxy = bool(entry.options.get("auto_proxy_webrtc", False))

    # Respect user-forced camera mode first
    cam_mode = entry.options.get("camera_mode")
    if cam_mode == "webrtc":
        async_add_entities([CrealityWebRTCCamera(coord, WEBRTC_URL_TEMPLATE.format(host=host), use_proxy=use_proxy)])
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
        async_add_entities([CrealityWebRTCCamera(coord, webrtc_url, use_proxy=use_proxy)])
        return

    # Otherwise, detect WebRTC by probing the signaling endpoint quickly
    if await _probe_webrtc_signaling(hass, webrtc_url, timeout=1.5):
        async_add_entities([CrealityWebRTCCamera(coord, webrtc_url, use_proxy=use_proxy)])
        return

    # Fallback to MJPEG for K1 family
    mjpeg_url = MJPEG_URL_TEMPLATE.format(host=host)
    async_add_entities([CrealityMjpegCamera(coord, mjpeg_url)])
