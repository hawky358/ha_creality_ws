from __future__ import annotations

import json
import logging
from typing import Any

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .ws_client import K1CClient
from .const import DOMAIN, STALE_AFTER_SECS

_LOGGER = logging.getLogger(__name__)


class K1CCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Central store + transport wrapper."""

    def __init__(self, hass, host: str):
        super().__init__(hass, _LOGGER, name=f"{DOMAIN}@{host}", update_interval=None)
        self.client = K1CClient(host, self._handle_message)
        self.data: dict[str, Any] = {}
        self._paused_flag = False
        self._last_avail = False

    # -------- lifecycle --------
    async def async_start(self) -> None:
        await self.client.start()

    async def async_stop(self) -> None:
        await self.client.stop()

    async def wait_first_connect(self, timeout: float = 5.0) -> bool:
        return await self.client.wait_first_connect(timeout=timeout)

    def check_stale(self) -> None:
        now_avail = self.available
        if now_avail != self._last_avail:
            self._last_avail = now_avail
            self.async_update_listeners()

    # -------- availability --------
    @property
    def available(self) -> bool:
        return (self.hass.loop.time() - self.client.last_rx_monotonic()) < STALE_AFTER_SECS

    # -------- pause flag --------
    def mark_paused(self, paused: bool) -> None:
        self._paused_flag = bool(paused)
        self.async_update_listeners()

    def paused_flag(self) -> bool:
        return self._paused_flag

    # -------- inbound frame handler --------
    async def _handle_message(self, payload: dict[str, Any]) -> None:
        # Merge raw frame into coordinator data
        self.data.update(payload)

        # Parse stringified JSON lists for objects/exclusions
        try:
            objs_raw = self.data.get("objects")
            exc_raw = self.data.get("excluded_objects")
            if isinstance(objs_raw, str) and objs_raw.strip().startswith("["):
                self.data["objects_list"] = json.loads(objs_raw)
            if isinstance(exc_raw, str) and exc_raw.strip().startswith("["):
                self.data["excluded_objects_list"] = json.loads(exc_raw)
        except Exception:
            pass

        # If a job looks active again, clear manual paused flag
        if (self.data.get("printStartTime") or self.data.get("printFileName")) and (
            (self.data.get("printProgress") or self.data.get("dProgress") or 0) > 0
            or (self.data.get("printJobTime") or 0) > 0
        ):
            self._paused_flag = False

        self.async_update_listeners()
