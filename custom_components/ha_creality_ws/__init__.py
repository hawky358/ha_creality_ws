from __future__ import annotations
import logging
import json
import os
from datetime import datetime, timedelta
from typing import Callable, List, Optional, Any

from homeassistant.config_entries import ConfigEntry #type: ignore[import]
from homeassistant.core import HomeAssistant, ServiceCall #type: ignore[import]
from homeassistant.exceptions import ConfigEntryNotReady #type: ignore[import]
from homeassistant.helpers.event import ( #type: ignore[import]
    async_track_time_interval,
    async_track_state_change_event,
)
import voluptuous as vol #type: ignore[import]

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

    # Register the Lovelace card (non-fatal on failure)
    try:
        card_register = CrealityCardRegistration(hass)
        await card_register.async_register()
    except Exception as exc:
        _LOGGER.warning("Lovelace card registration skipped due to error: %s", exc)

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
    
    # Register diagnostic service (only once per integration)
    if not hasattr(hass.data[DOMAIN], '_diagnostic_service_registered'):
        await _register_diagnostic_service(hass)
        hass.data[DOMAIN]['_diagnostic_service_registered'] = True
    
    _LOGGER.info("ha_creality_ws: setup complete")
    return True


async def _register_diagnostic_service(hass: HomeAssistant) -> None:
    """Register the diagnostic service for dumping WebSocket telemetry data."""
    
    async def diagnostic_dump(call: ServiceCall) -> None:
        """Dump all WebSocket telemetry data to a JSON file."""
        try:
            # Get all coordinators (all printer instances)
            coordinators: List[tuple[str, KCoordinator]] = []
            for entry_id, coord in hass.data[DOMAIN].items():
                if isinstance(coord, KCoordinator):
                    coordinators.append((entry_id, coord))
            
            if not coordinators:
                _LOGGER.error("No Creality printers found to dump data from")
                return
            
            # Create diagnostic data structure
            diagnostic_data = {
                "timestamp": datetime.now().isoformat(),
                "home_assistant_version": getattr(hass.config, 'version', 'unknown'),
                "integration_version": "0.5.4",  # Update this when version changes
                "printers": {}
            }
            
            for entry_id, coord in coordinators:
                printer_data = {
                    "host": coord.client._host,
                    "available": coord.available,
                    "power_is_off": coord.power_is_off(),
                    "paused_flag": coord.paused_flag(),
                    "pending_pause": coord.pending_pause(),
                    "pending_resume": coord.pending_resume(),
                    "last_rx_time": coord.client.last_rx_monotonic(),
                    "telemetry_data": coord.data.copy() if coord.data else {}
                }
                
                # Add model detection info
                model = (coord.data or {}).get("model") or ""
                model_l = str(model).lower()
                printer_data["model_detection"] = {
                    "raw_model": model,
                    "model_lower": model_l,
                    "is_k1_family": "k1" in model_l,
                    "is_k1_se": "k1" in model_l and "se" in model_l,
                    "is_k1_max": "k1" in model_l and "max" in model_l,
                    "is_k2_family": "k2" in model_l,
                    "is_k2_base": "k2" in model_l and not ("pro" in model_l or "plus" in model_l),
                    "is_k2_pro": "k2" in model_l and "pro" in model_l,
                    "is_k2_plus": "k2" in model_l and "plus" in model_l,
                    "is_ender_v3_family": "ender" in model_l and "v3" in model_l,
                    "is_creality_hi": "hi" in model_l
                }
                
                # Add feature detection (matching sensor.py logic)
                is_k1_family = "k1" in model_l
                is_k1_se = is_k1_family and "se" in model_l
                is_k1_max = is_k1_family and "max" in model_l
                is_k2_family = "k2" in model_l
                is_k2_pro = is_k2_family and "pro" in model_l
                is_k2_plus = is_k2_family and "plus" in model_l
                is_ender_v3_family = "ender" in model_l and "v3" in model_l
                is_creality_hi = "hi" in model_l
                
                printer_data["feature_detection"] = {
                    "has_light": not (is_k1_se or is_ender_v3_family),
                    "has_box_sensor": (is_k1_family and not is_k1_se) or is_k1_max or is_k2_family or is_creality_hi,
                    "has_box_control": is_k2_pro or is_k2_plus,
                    "camera_type": "webrtc" if is_k2_family else 
                                  "mjpeg_optional" if (is_k1_se or is_ender_v3_family) else 
                                  "mjpeg"
                }
                
                diagnostic_data["printers"][entry_id] = printer_data
            
            # Convert to JSON string for UI display
            json_output = json.dumps(diagnostic_data, indent=2, ensure_ascii=False)
            
            
            # Log the diagnostic data to make it visible in Home Assistant logs (using WARNING level for visibility)
            _LOGGER.warning("=== CREALITY DIAGNOSTIC DATA START ===" + json_output + "=== CREALITY DIAGNOSTIC DATA END ===")
            
            # Create a persistent notification with summary (without await since it's not async)
            from homeassistant.components.persistent_notification import async_create
            async_create(
                hass,
                title="Creality Diagnostic Data",
                message=f"Diagnostic data collected for {len(diagnostic_data['printers'])} printer(s). Data size: {len(json_output)} bytes. Check the logs for the full JSON data.",
                notification_id="creality_diagnostic_data"
            )
                
        except Exception as exc:
            _LOGGER.exception("Failed to create diagnostic dump: %s", exc)
            if hasattr(call, 'response'):
                call.response = {"error": str(exc)}
    
    # Register the service
    schema = vol.Schema({
        vol.Optional("include_sensitive_data", default=False): bool,
    })
    
    hass.services.async_register(
        DOMAIN, 
        "diagnostic_dump", 
        diagnostic_dump, 
        schema=schema
    )
    
    _LOGGER.info("Diagnostic service registered: ha_creality_ws.diagnostic_dump")


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