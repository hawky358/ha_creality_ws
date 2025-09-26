from __future__ import annotations

import logging
import os
import shutil
from datetime import timedelta
from importlib import resources

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.event import async_track_time_interval

from .const import DOMAIN, STALE_AFTER_SECS
from .coordinator import K1CCoordinator

_LOGGER = logging.getLogger(__name__)
PLATFORMS: list[str] = ["sensor", "switch", "camera", "button", "number"]

def _copy_frontend(hass):
    try:
        target = hass.config.path("www", "ha_creality_ws")
        os.makedirs(target, exist_ok=True)
        pkg = resources.files(__package__) / "frontend"
        for name in ("k1c_printer_card.js",):  # single file
            with resources.as_file(pkg / name) as src:
                shutil.copy2(str(src), os.path.join(target, name))
        _LOGGER.debug("ha_creality_ws: copied /local/ha_creality_ws/k1c_printer_card.js")
    except Exception as exc:
        _LOGGER.warning("ha_creality_ws: failed to copy frontend file: %s", exc)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    host: str = entry.data["host"]
    coord = K1CCoordinator(hass, host=host)

    try:
        await coord.async_start()
        ok = await coord.wait_first_connect(timeout=8.0)
        if not ok:
            _LOGGER.warning("Creality WS: initial connect not confirmed; will retry in background")
    except Exception as exc:
        await coord.async_stop()
        raise ConfigEntryNotReady(str(exc)) from exc

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coord
    await hass.async_add_executor_job(_copy_frontend, hass)

    # periodic stale check
    def _interval_check(_now):
        coord.check_stale()

    hass.data[DOMAIN].setdefault("_intervals", [])
    cancel = async_track_time_interval(
        hass, _interval_check, timedelta(seconds=max(5, STALE_AFTER_SECS // 3))
    )
    hass.data[DOMAIN]["_intervals"].append(cancel)

    # ----- Services -----
    async def _get_coord(_call: ServiceCall) -> K1CCoordinator:
        return coord  # single-entry assumption

    async def _svc_pause(_call: ServiceCall) -> None:
        c = await _get_coord(_call)
        await c.client.send_set_retry(pause=1)
        c.mark_paused(True)

    async def _svc_resume(_call: ServiceCall) -> None:
        c = await _get_coord(_call)
        await c.client.send_set_retry(pause=0)
        c.mark_paused(False)

    async def _svc_stop(_call: ServiceCall) -> None:
        c = await _get_coord(_call)
        await c.client.send_set_retry(stop=1)
        c.mark_paused(False)

    async def _svc_home_xy_then_z(_call: ServiceCall) -> None:
        c = await _get_coord(_call)
        await c.client.send_set_retry(autohome="X Y")
        await c.client.send_set_retry(autohome="Z")

    async def _svc_light_on(_call: ServiceCall) -> None:
        c = await _get_coord(_call)
        await c.client.send_set_retry(lightSw=1)

    async def _svc_light_off(_call: ServiceCall) -> None:
        c = await _get_coord(_call)
        await c.client.send_set_retry(lightSw=0)

    async def _svc_light_toggle(_call: ServiceCall) -> None:
        c = await _get_coord(_call)
        cur = bool((c.data or {}).get("lightSw", 0))
        await c.client.send_set_retry(lightSw=0 if cur else 1)

    hass.services.async_register(DOMAIN, "pause_print", _svc_pause)
    hass.services.async_register(DOMAIN, "resume_print", _svc_resume)
    hass.services.async_register(DOMAIN, "stop_print", _svc_stop)
    hass.services.async_register(DOMAIN, "home_xy_then_z", _svc_home_xy_then_z)
    hass.services.async_register(DOMAIN, "light_on", _svc_light_on)
    hass.services.async_register(DOMAIN, "light_off", _svc_light_off)
    hass.services.async_register(DOMAIN, "light_toggle", _svc_light_toggle)

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
