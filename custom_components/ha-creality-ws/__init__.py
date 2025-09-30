from __future__ import annotations

import logging
import os
import shutil
from datetime import timedelta
from importlib import resources
from typing import Callable, List, Optional

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.event import (
    async_track_time_interval,
    async_track_state_change_event,
)

from .const import DOMAIN, STALE_AFTER_SECS, CONF_POWER_SWITCH
from .coordinator import K1CCoordinator

_LOGGER = logging.getLogger(__name__)
PLATFORMS: list[str] = ["sensor", "switch", "camera", "button", "number"]


def _copy_frontend(hass: HomeAssistant) -> None:
    """Copy card assets to /local/ha_creality_ws/."""
    try:
        target = hass.config.path("www", "ha_creality_ws")
        os.makedirs(target, exist_ok=True)
        pkg = resources.files(__package__) / "frontend"
        for name in ("k1c_printer_card.js",):
            with resources.as_file(pkg / name) as src:
                shutil.copy2(str(src), os.path.join(target, name))
        _LOGGER.debug(
            "ha_creality_ws: copied /local/ha_creality_ws/k1c_printer_card.js"
        )
    except Exception as exc:
        _LOGGER.warning("ha_creality_ws: failed to copy frontend file: %s", exc)


async def _options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Apply options (power switch) to the coordinator at runtime."""
    coord: K1CCoordinator = hass.data[DOMAIN][entry.entry_id]
    coord.set_power_switch(entry.options.get(CONF_POWER_SWITCH))


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    host: str = entry.data["host"]
    power_switch = entry.options.get(CONF_POWER_SWITCH)
    coord = K1CCoordinator(hass, host=host, power_switch=power_switch)

    try:
        await coord.async_start()
        ok = await coord.wait_first_connect(timeout=8.0)
        if not ok:
            _LOGGER.warning(
                "Creality WS: initial connect not confirmed; will retry in background"
            )
    except Exception as exc:
        await coord.async_stop()
        raise ConfigEntryNotReady(str(exc)) from exc

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coord
    entry.async_on_unload(entry.add_update_listener(_options_updated))

    await hass.async_add_executor_job(_copy_frontend, hass)

    # periodic stale check — flip to 'unknown' when no frames for STALE_AFTER_SECS
    def _interval_check(_now) -> None:
        """
        Periodically checks for a stale connection AND forces a general state update.
        This ensures that missed events (like a power switch turning off) are eventually caught.
        """
        # First, check for WebSocket staleness. This updates the `available` property.
        coord.check_stale()

        # Second, and most importantly, force ALL entities to re-evaluate their state.
        # This ensures they will re-run their logic against the latest `power_is_off()`
        # and `available` properties, catching any state that was missed between events.
        coord.async_update_listeners()

    hass.data[DOMAIN].setdefault("_intervals", [])
    # The interval is already set to a reasonable value (e.g., every 5 seconds)
    cancel = async_track_time_interval(
        hass, _interval_check, timedelta(seconds=max(5, STALE_AFTER_SECS // 3))
    )
    hass.data[DOMAIN]["_intervals"].append(cancel)

    # live refresh when the configured power switch changes
    _unsubs: List[Callable[[], None]] = []

    def _watch_power_switch(entity_id: Optional[str]) -> None:
        # clear previous watchers
        while _unsubs:
            _unsubs.pop()()
        if not entity_id:
            _LOGGER.debug("ha_creality_ws: no power switch configured; watcher disabled")
            return

        _LOGGER.debug("ha_creality_ws: watching power switch: %s", entity_id)

        def _state_cb(event) -> None:
            # Switch state flipped -> recalc all derived states (status/zeroing)
            coord.async_update_listeners()

        _unsubs.append(
            async_track_state_change_event(hass, [entity_id], _state_cb)
        )

    _watch_power_switch(power_switch)

    async def _options_listener(_hass: HomeAssistant, new_entry: ConfigEntry) -> None:
        ps = new_entry.options.get(CONF_POWER_SWITCH)
        coord.set_power_switch(ps)
        _watch_power_switch(ps)

    entry.async_on_unload(entry.add_update_listener(_options_listener))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _LOGGER.info("ha_creality_ws: setup complete")
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coord: K1CCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
    await coord.async_stop()
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if DOMAIN in hass.data and not hass.data[DOMAIN]:
        for cancel in hass.data[DOMAIN].get("_intervals", []):
            cancel()
        hass.data.pop(DOMAIN, None)
    return ok
