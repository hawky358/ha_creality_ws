from __future__ import annotations
import logging
from datetime import timedelta
from typing import Callable, List, Optional

from homeassistant.config_entries import ConfigEntry #type: ignore[import]
from homeassistant.core import HomeAssistant, CoreState #type: ignore[import]
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED #type: ignore[import]
from homeassistant.exceptions import ConfigEntryNotReady #type: ignore[import]
from homeassistant.helpers.event import ( #type: ignore[import]
    async_track_time_interval,
    async_track_state_change_event,
)

from .const import DOMAIN, STALE_AFTER_SECS, CONF_POWER_SWITCH
from .coordinator import KCoordinator
from .frontend import CrealityCardRegistration  # <-- NEW IMPORT

_LOGGER = logging.getLogger(__name__)
PLATFORMS: list[str] = ["sensor", "switch", "camera", "button", "number"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the Creality integration from a config entry."""
    host: str = entry.data["host"]
    power_switch = entry.options.get(CONF_POWER_SWITCH)
    coord = KCoordinator(hass, host=host, power_switch=power_switch)

    try:
        await coord.async_start()
        # If printer is OFF, we intentionally don’t wait for connectivity.
        if not coord.power_is_off():
            ok = await coord.wait_first_connect(timeout=8.0)
            if not ok:
                _LOGGER.warning("Initial connect not confirmed; will retry in background")
    except Exception as exc:
        await coord.async_stop()
        raise ConfigEntryNotReady(str(exc)) from exc

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coord

    # Register the Lovelace card after Home Assistant startup to avoid a
    # race condition in the Lovelace storage manager that can overwrite
    # existing .storage/lovelace_resources if resources are created too
    # early during startup. If Home Assistant is already running, run
    # immediately.
    card_register = CrealityCardRegistration(hass)

    async def _do_register(_event=None) -> None:
        try:
            await card_register.async_register()
        except Exception as exc:  # non-fatal
            _LOGGER.warning("Lovelace card registration skipped due to error: %s", exc)

    if hass.state == CoreState.running:
        # HA already started; register now
        hass.async_create_task(_do_register())
    else:
        # Defer until HA has finished starting up
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, lambda event: hass.async_create_task(_do_register(event)))

    # Listener for options updates
    entry.async_on_unload(entry.add_update_listener(options_update_listener))

    # Periodic state checker
    def _interval_check(_now) -> None:
        coord.check_stale()
        hass.loop.call_soon_threadsafe(coord.async_update_listeners)
    
    cancel_interval = async_track_time_interval(
        hass, _interval_check, timedelta(seconds=max(5, STALE_AFTER_SECS // 3))
    )
    entry.async_on_unload(cancel_interval)

    # Watcher for power switch state changes
    def _watch_power_switch(entity_id: Optional[str]) -> Callable:
        if not entity_id:
            return lambda: None
        
        async def _state_cb(event) -> None:
            await coord.async_handle_power_change()

        return async_track_state_change_event(hass, [entity_id], _state_cb)

    cancel_power_watch = _watch_power_switch(power_switch)
    entry.async_on_unload(cancel_power_watch)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _LOGGER.info("ha_creality_ws: setup complete")
    return True


async def options_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    coord: KCoordinator = hass.data[DOMAIN][entry.entry_id]
    await coord.async_stop()

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    # If this is the last instance of the integration, unregister the card
    if not hass.data[DOMAIN]:
        card_register = CrealityCardRegistration(hass)
        await card_register.async_unregister()

    return unload_ok