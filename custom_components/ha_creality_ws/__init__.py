from __future__ import annotations
import logging
import json
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
from .frontend import CrealityCardRegistration
from .utils import ModelDetection

_LOGGER = logging.getLogger(__name__)
PLATFORMS: list[str] = ["sensor", "switch", "camera", "button", "number"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the Creality integration from a config entry."""
    host: str = entry.data["host"]
    power_switch = entry.options.get(CONF_POWER_SWITCH)
    coord = KCoordinator(hass, host=host, power_switch=power_switch)

    try:
        await coord.async_start()
        # If printer is OFF, we intentionally don't wait for connectivity.
        if not coord.power_is_off():
            ok = await coord.wait_first_connect(timeout=8.0)
            if not ok:
                _LOGGER.warning("Initial connect not confirmed; will retry in background")
    except Exception as exc:
        await coord.async_stop()
        raise ConfigEntryNotReady(str(exc)) from exc

    # Detect and store device info during initial setup (only once)
    # This is stored in entry.data which persists across restarts
    if not entry.data.get("_device_info_cached"):
        _LOGGER.info("Performing initial device detection for %s", host)
        # Wait a bit longer to ensure we get model info
        if not coord.power_is_off():
            ok = await coord.wait_first_connect(timeout=10.0)
            if ok and coord.data:
                # Store device info in entry data
                model = coord.data.get("model") or "K by Creality"
                hostname = coord.data.get("hostname")
                model_version = coord.data.get("modelVersion")
                
                printermodel = ModelDetection(coord.data)
                new_data = dict(entry.data)
                new_data["_device_info_cached"] = True
                new_data["_cached_model"] = model
                new_data["_cached_hostname"] = hostname
                new_data["_cached_model_version"] = model_version
                new_data["_cached_has_light"] = printermodel.has_light
                new_data["_cached_has_box_sensor"] = printermodel.has_box_sensor
                new_data["_cached_has_box_control"] = printermodel.has_box_control
                new_data["_cached_camera_type"] = "webrtc" if printermodel.is_k2_family else (
                    "mjpeg_optional" if (printermodel.is_k1_se or printermodel.is_ender_v3_family) else "mjpeg"
                )
                hass.config_entries.async_update_entry(entry, data=new_data)
                _LOGGER.info("Device info cached: model=%s, camera=%s", model, new_data.get("_cached_camera_type"))
        else:
            # Printer is off, cache defaults
            _LOGGER.info("Printer is off during first setup, caching default device info")
            new_data = dict(entry.data)
            new_data["_device_info_cached"] = True
            new_data["_cached_model"] = "K by Creality"
            new_data["_cached_has_light"] = True
            new_data["_cached_has_box_sensor"] = False
            new_data["_cached_has_box_control"] = False
            new_data["_cached_camera_type"] = "mjpeg"
            hass.config_entries.async_update_entry(entry, data=new_data)

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coord
    
    # Store entry_id in coordinator for easy access
    coord._config_entry_id = entry.entry_id

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
    """Register diagnostic service - outputs all data to logs (no file storage)."""
    
    async def diagnostic_dump(call: ServiceCall) -> None:
        """Collect and log telemetry data for all printers."""
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
                printermodel = ModelDetection(coord.data)
                model = (coord.data or {}).get("model") or ""
                model_l = str(model).lower()
                printer_data["model_detection"] = {
                    "raw_model": model,
                    "model_lower": model_l,
                    "is_k1_family": printermodel.is_k1_family,
                    "is_k1_se": printermodel.is_k1_se,
                    "is_k1_max": printermodel.is_k1_max,
                    "is_k2_family": printermodel.is_k2_family,
                    "is_k2_base": printermodel.is_k2_base,
                    "is_k2_pro": printermodel.is_k2_pro,
                    "is_k2_plus": printermodel.is_k2_plus,
                    "is_ender_v3_family": printermodel.is_ender_v3_family,
                    "is_creality_hi": printermodel.is_creality_hi
                }
                
                # Add feature detection (matching sensor.py logic)
                printer_data["feature_detection"] = {
                    "has_light": printermodel.has_light,
                    "has_box_sensor": printermodel.has_box_sensor,
                    "has_box_control": printermodel.has_box_control,
                    "camera_type": "webrtc" if printermodel.is_k2_family else 
                                  "mjpeg_optional" if (printermodel.is_k1_se or printermodel.is_ender_v3_family) else 
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