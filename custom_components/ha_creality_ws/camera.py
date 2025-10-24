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


class _FeatureMask(int):
    """Custom feature mask that supports the 'in' operator."""
    def __contains__(self, feature):
        return bool(self & feature)


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
    """WebRTC camera that uses go2rtc to convert WebRTC stream to MJPEG.

    This camera integrates with Home Assistant's go2rtc instance to:
    1. Configure go2rtc to pull WebRTC stream from the Creality K2 printer
    2. Expose the go2rtc MJPEG stream as a native Home Assistant camera
    3. Provide both static images and streaming capabilities
    """

    def __init__(self, coordinator, signaling_url: str, use_proxy: bool = False) -> None:
        super().__init__(coordinator, "Printer Camera", "camera")
        self._upstream_signaling_url = signaling_url
        self._use_proxy = use_proxy
        self._go2rtc_url: str | None = None
        self._stream_name: str | None = None
        self._last_error: str | None = None
        
        # Set up supported features for MJPEG streaming
        self._setup_supported_features()

    def _setup_supported_features(self) -> None:
        """Set up camera features for WebRTC cameras with go2rtc streaming."""
        mask = 0
        if "CameraEntityFeature" in globals() and CameraEntityFeature is not None:
            # Include STREAM for MJPEG streaming via go2rtc
            stream_val = getattr(CameraEntityFeature, "STREAM", None)
            if stream_val is not None:
                try:
                    mask |= int(stream_val)
                except Exception:
                    pass
            
            # Include ON_DEMAND for static image capability
            ond_val = getattr(CameraEntityFeature, "ON_DEMAND", None)
            if ond_val is not None:
                try:
                    mask |= int(ond_val)
                except Exception:
                    pass

        self._attr_supported_features = _FeatureMask(mask)
        _LOGGER.info("ha_creality_ws: WebRTC camera features: STREAM=%s, ON_DEMAND=%s, mask=%d", 
                    bool(mask & 2), bool(mask & 1), mask)  # STREAM is bit 1 (2), ON_DEMAND is bit 0 (1)

    async def async_added_to_hass(self) -> None:
        """Configure go2rtc stream when camera is added to Home Assistant."""
        await super().async_added_to_hass()
        
        # Get go2rtc URL and configure the stream
        self._go2rtc_url = await self._get_go2rtc_url()
        if self._go2rtc_url:
            await self._configure_go2rtc_stream()
        else:
            _LOGGER.warning("ha_creality_ws: go2rtc not available, WebRTC camera will use fallback images")

    async def async_camera_image(
        self,
        width: Optional[int] = None,
        height: Optional[int] = None,
    ) -> bytes | None:
        """Return a single camera image from go2rtc."""
        if not self._go2rtc_url or not self._stream_name:
            return await self._fallback_image()

        try:
            session = async_get_clientsession(self.hass)
            # Request a single frame from go2rtc using the correct API endpoint
            # According to the API docs: GET /api/frame.jpeg?src=stream_name
            image_url = f"{self._go2rtc_url.rstrip('/')}/api/frame.jpeg?src={self._stream_name}"
            
            async with session.get(image_url, timeout=5) as response:
                if response.status == 200:
                    image_data = await response.read()
                    if self._is_valid_jpeg(image_data):
                        self._last_frame = image_data
                        return image_data
                    else:
                        _LOGGER.warning("ha_creality_ws: invalid JPEG from go2rtc")
                else:
                    _LOGGER.warning("ha_creality_ws: go2rtc frame returned status %d", response.status)
        except ClientError as err:
            _LOGGER.warning("ha_creality_ws: failed to get image from go2rtc: %s", err)
        except asyncio.TimeoutError:
            _LOGGER.warning("ha_creality_ws: timeout getting image from go2rtc")
        except Exception as exc:
            _LOGGER.warning("ha_creality_ws: unexpected error getting image from go2rtc: %s", exc)
        
        return await self._fallback_image()

    async def handle_async_mjpeg_stream(self, request):
        """Return an MJPEG stream from go2rtc."""
        if not self._go2rtc_url or not self._stream_name:
            _LOGGER.warning("ha_creality_ws: go2rtc not available for streaming")
            return web.Response(status=503, text="go2rtc not available")

        try:
            session = async_get_clientsession(self.hass)
            # Get MJPEG stream from go2rtc using the correct API endpoint
            # According to the API docs: GET /api/stream.mjpeg?src=stream_name
            mjpeg_stream_url = f"{self._go2rtc_url.rstrip('/')}/api/stream.mjpeg?src={self._stream_name}"
            
            _LOGGER.debug("ha_creality_ws: proxying MJPEG stream from go2rtc: %s", mjpeg_stream_url)
            
            async with session.get(mjpeg_stream_url, timeout=None) as response:
                if response.status != 200:
                    _LOGGER.warning("ha_creality_ws: go2rtc MJPEG stream returned status %d", response.status)
                    return web.Response(status=502, text="Upstream go2rtc stream error")

                # Stream the content directly to the client
                return web.Response(
                    status=200,
                    headers={"Content-Type": "multipart/x-mixed-replace;boundary=--frame"},
                    body=response.content,
                )
        except ClientError as err:
            _LOGGER.error("ha_creality_ws: failed to proxy go2rtc MJPEG stream: %s", err)
            return web.Response(status=502, text="Upstream go2rtc stream error")
        except asyncio.TimeoutError:
            _LOGGER.error("ha_creality_ws: timeout while proxying go2rtc MJPEG stream")
            return web.Response(status=504, text="Upstream go2rtc stream timeout")
        except Exception as exc:
            _LOGGER.error("ha_creality_ws: unexpected error proxying go2rtc MJPEG stream: %s", exc)
            return web.Response(status=502, text="Upstream go2rtc stream error")

    async def _get_go2rtc_url(self) -> str | None:
        """Get the go2rtc URL using built-in Home Assistant features."""
        try:
            # go2rtc is a built-in Home Assistant service, always available on localhost:11984
            # when running as part of Home Assistant core
            _LOGGER.info("ha_creality_ws: using built-in go2rtc service on localhost:11984")
            return "http://localhost:11984"

        except Exception as exc:
            _LOGGER.warning("ha_creality_ws: failed to get go2rtc URL: %s", exc)
            return None

    async def _configure_go2rtc_stream(self) -> None:
        """Configure go2rtc to pull the WebRTC stream from the printer using native Creality support."""
        if not self._go2rtc_url:
            return
            
        # Create a unique stream name for this printer
        printer_host = self._upstream_signaling_url.split("://")[1].split(":")[0]
        self._stream_name = f"creality_k2_{printer_host.replace('.', '_')}"
        
        # Use the native Creality WebRTC format that go2rtc 1.9.9+ supports
        # Based on the client_creality.go implementation, go2rtc has built-in support
        webrtc_printer_url = self._upstream_signaling_url
        go2rtc_src = f"webrtc:{webrtc_printer_url}"
        
        _LOGGER.info("ha_creality_ws: configuring go2rtc stream '%s' with native Creality support: '%s'", 
                    self._stream_name, go2rtc_src)
        
        try:
            # Use the go2rtc configuration API to add the stream
            # This is the proper way to configure streams in go2rtc
            session = async_get_clientsession(self.hass)
            api_url = f"{self._go2rtc_url.rstrip('/')}/api/config"
            
            # Configure the stream in go2rtc's config
            config_payload = {"streams": {self._stream_name: go2rtc_src}}
            
            async with session.post(api_url, json=config_payload, timeout=10) as response:
                if response.status in [200, 201, 204]:
                    _LOGGER.info("ha_creality_ws: successfully configured go2rtc stream '%s' with native Creality support", 
                                self._stream_name)
                else:
                    response_text = await response.text()
                    _LOGGER.warning("ha_creality_ws: go2rtc configuration failed, status: %d, response: %s", 
                                  response.status, response_text)
                    self._last_error = f"go2rtc configuration failed: HTTP {response.status}"
                    
        except Exception as exc:
            _LOGGER.error("ha_creality_ws: failed to configure go2rtc stream: %s", exc)
            self._last_error = f"go2rtc configuration error: {exc}"

    @property
    def extra_state_attributes(self) -> dict:
        """Return extra state attributes for the camera."""
        attrs = {
            "go2rtc_url": self._go2rtc_url,
            "go2rtc_stream_name": self._stream_name,
            "upstream_signaling_url": self._upstream_signaling_url,
            "webrtc_using_proxy": self._use_proxy,
        }
        if self._last_error:
            attrs["error"] = self._last_error
        return attrs

    def _is_valid_jpeg(self, data: bytes) -> bool:
        """Check if the data is a valid JPEG image."""
        if not data or len(data) < 20:
            return False
        return data.startswith(b"\xff\xd8") and data.endswith(b"\xff\xd9")


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

    # Model detection logic
    is_k1_family = "k1" in model_l
    is_k1_se = is_k1_family and "se" in model_l
    is_k1_max = is_k1_family and "max" in model_l
    is_k2_family = "k2" in model_l
    is_k2_base = is_k2_family and not ("pro" in model_l or "plus" in model_l)
    is_k2_pro = is_k2_family and "pro" in model_l
    is_k2_plus = is_k2_family and "plus" in model_l
    is_ender_v3_family = "ender" in model_l and "v3" in model_l
    is_creality_hi = "hi" in model_l

    # WebRTC cameras (K2 family - always present)
    webrtc_url = WEBRTC_URL_TEMPLATE.format(host=host)
    if is_k2_family:
        async_add_entities([CrealityWebRTCCamera(coord, webrtc_url, use_proxy=use_proxy)])
        return

    # MJPEG cameras with optional handling
    mjpeg_url = MJPEG_URL_TEMPLATE.format(host=host)
    
    # Models with optional cameras (K1 SE, Ender 3 V3 family)
    if is_k1_se or is_ender_v3_family:
        try:
            async_add_entities([CrealityMjpegCamera(coord, mjpeg_url)])
        except Exception:
            # Camera is optional for these models, continue without it
            pass
        return

    # Models with default MJPEG cameras (K1 family except SE, K1 Max, Creality Hi)
    if is_k1_family or is_k1_max or is_creality_hi:
        async_add_entities([CrealityMjpegCamera(coord, mjpeg_url)])
        return

    # Otherwise, detect WebRTC by probing the signaling endpoint quickly
    if await _probe_webrtc_signaling(hass, webrtc_url, timeout=1.5):
        async_add_entities([CrealityWebRTCCamera(coord, webrtc_url, use_proxy=use_proxy)])
        return

    # Fallback to MJPEG
    async_add_entities([CrealityMjpegCamera(coord, mjpeg_url)])
