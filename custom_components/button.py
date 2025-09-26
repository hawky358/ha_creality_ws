from __future__ import annotations

import asyncio
from homeassistant.components.button import ButtonEntity

from .entity import K1CEntity
from .const import DOMAIN


async def async_setup_entry(hass, entry, async_add_entities):
    coord = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        K1CHomeAllButton(coord),
        K1CPrintPauseButton(coord),
        K1CPrintResumeButton(coord),
        K1CPrintStopButton(coord),
    ])


class K1CHomeAllButton(K1CEntity, ButtonEntity):
    _attr_name = "Home (XY then Z)"
    _attr_icon = "mdi:home-circle"

    def __init__(self, coordinator):
        super().__init__(coordinator, self._attr_name, "home_all")
        self._seq_lock = asyncio.Lock()

    async def async_press(self) -> None:
        async with self._seq_lock:
            await self.coordinator.client.send_set_retry(autohome="X Y")
            await asyncio.sleep(1.0)
            await self._wait_until_idle_or_timeout(15.0)
            await self.coordinator.client.send_set_retry(autohome="Z")

    async def _wait_until_idle_or_timeout(self, timeout: float) -> None:
        end = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < end:
            if (self.coordinator.data or {}).get("deviceState") != 7:
                return
            await asyncio.sleep(0.25)


class _BasePrintButton(K1CEntity, ButtonEntity):
    _attr_icon = "mdi:printer-3d"

    def __init__(self, coordinator, name: str, uid: str):
        super().__init__(coordinator, name, uid)


class K1CPrintPauseButton(_BasePrintButton):
    def __init__(self, coordinator):
        super().__init__(coordinator, "Pause Print", "pause_print")

    async def async_press(self) -> None:
        await self.coordinator.client.send_set_retry(pause=1)
        self.coordinator.mark_paused(True)


class K1CPrintResumeButton(_BasePrintButton):
    def __init__(self, coordinator):
        super().__init__(coordinator, "Resume Print", "resume_print")

    async def async_press(self) -> None:
        # Assumption: pause=0 resumes
        await self.coordinator.client.send_set_retry(pause=0)
        self.coordinator.mark_paused(False)


class K1CPrintStopButton(_BasePrintButton):
    def __init__(self, coordinator):
        super().__init__(coordinator, "Stop Print", "stop_print")

    async def async_press(self) -> None:
        await self.coordinator.client.send_set_retry(stop=1)
        # Clear paused; job is no longer active
        self.coordinator.mark_paused(False)
