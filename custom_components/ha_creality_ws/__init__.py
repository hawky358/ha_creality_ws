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

from .const import (
    DOMAIN, 
    STALE_AFTER_SECS, 
    CONF_POWER_SWITCH,
    CONF_GO2RTC_URL,
    CONF_GO2RTC_PORT,
    DEFAULT_GO2RTC_URL,
    DEFAULT_GO2RTC_PORT,
)
from .coordinator import KCoordinator
from .frontend import CrealityCardRegistration
from .utils import ModelDetection

_LOGGER = logging.getLogger(__name__)
PLATFORMS: list[str] = ["sensor", "switch", "camera", "button", "number"]

# Import integration version from manifest
import json
import os

async def _get_integration_version(hass: HomeAssistant) -> str:
    """Get current integration version from manifest.json"""
    try:
        manifest_path = os.path.join(os.path.dirname(__file__), "manifest.json")
        # Use Home Assistant's async file operations
        content = await hass.async_add_executor_job(
            lambda: open(manifest_path, "r").read()
        )
        manifest = json.loads(content)
        return manifest.get("version", "0.0.0")
    except Exception:
        return "0.0.0"

def _migrate_go2rtc_settings(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Migrate go2rtc settings to entry options if not already set."""
    current_options = dict(entry.options)
    needs_update = False
    
    # Migrate go2rtc_url if missing or in data
    if not current_options.get(CONF_GO2RTC_URL):
        # Check if it was stored in entry.data (old location)
        old_url = entry.data.get(CONF_GO2RTC_URL)
        if old_url:
            current_options[CONF_GO2RTC_URL] = old_url
            needs_update = True
            _LOGGER.info("Migrated go2rtc_url from entry.data to options")
        else:
            # Set default if missing
            current_options[CONF_GO2RTC_URL] = DEFAULT_GO2RTC_URL
            needs_update = True
            _LOGGER.debug("Setting default go2rtc_url: %s", DEFAULT_GO2RTC_URL)
    
    # Migrate go2rtc_port if missing or in data
    if not current_options.get(CONF_GO2RTC_PORT):
        # Check if it was stored in entry.data (old location)
        old_port = entry.data.get(CONF_GO2RTC_PORT)
        if old_port:
            current_options[CONF_GO2RTC_PORT] = old_port
            needs_update = True
            _LOGGER.info("Migrated go2rtc_port from entry.data to options")
        else:
            # Set default if missing
            current_options[CONF_GO2RTC_PORT] = DEFAULT_GO2RTC_PORT
            needs_update = True
            _LOGGER.debug("Setting default go2rtc_port: %s", DEFAULT_GO2RTC_PORT)
    
    if needs_update:
        hass.config_entries.async_update_entry(entry, options=current_options)
        _LOGGER.info("Migrated go2rtc settings to entry options")

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

    # Get current integration version
    current_version = await _get_integration_version(hass)
    cached_version = entry.data.get("_cached_version", "0.0.0")
    
    # Detect and store device info during initial setup or on version upgrade
    # This is stored in entry.data which persists across restarts
    should_re_cache = (
        not entry.data.get("_device_info_cached") or
        cached_version != current_version
    )
    
    # Also re-cache if max temperature values are missing (migration from older versions)
    should_re_cache = should_re_cache or (
        entry.data.get("_cached_max_bed_temp") is None or
        entry.data.get("_cached_max_nozzle_temp") is None
    )
    
    if should_re_cache:
        _LOGGER.info(
            "Caching device info for %s (cached_version=%s, current_version=%s)",
            host, cached_version, current_version
        )
        # Wait a bit longer to ensure we get model info
        if not coord.power_is_off():
            ok = await coord.wait_first_connect(timeout=10.0)
            if ok and coord.data:
                # Store device info in entry data
                printermodel = ModelDetection(coord.data)
                model = printermodel.friendly_name or "K by Creality"
                hostname = coord.data.get("hostname")
                model_version = coord.data.get("modelVersion")
                new_data = dict(entry.data)
                new_data["_device_info_cached"] = True
                new_data["_cached_version"] = current_version
                new_data["_cached_model"] = model
                new_data["_cached_hostname"] = hostname
                new_data["_cached_model_version"] = model_version
                new_data["_cached_has_light"] = printermodel.has_light
                new_data["_cached_has_box_sensor"] = printermodel.has_box_sensor
                new_data["_cached_has_box_control"] = printermodel.has_box_control
                
                # Cache max temperature values for temperature control limits
                new_data["_cached_max_bed_temp"] = coord.data.get("maxBedTemp")
                new_data["_cached_max_nozzle_temp"] = coord.data.get("maxNozzleTemp")
                new_data["_cached_max_box_temp"] = coord.data.get("maxBoxTemp")  # May be None for printers without heated chamber
                
                # Re-detect camera type if upgrading or missing
                cached_camera_type = entry.data.get("_cached_camera_type")
                if not cached_camera_type or cached_version != current_version:
                    new_data["_cached_camera_type"] = "webrtc" if printermodel.is_k2_family else (
                        "mjpeg_optional" if (printermodel.is_k1_se or printermodel.is_ender_v3_family) else "mjpeg"
                    )
                    _LOGGER.info("Camera type detected: %s", new_data["_cached_camera_type"])
                else:
                    # Keep existing camera type
                    new_data["_cached_camera_type"] = cached_camera_type
                
                hass.config_entries.async_update_entry(entry, data=new_data)
                _LOGGER.info(
                    "Device info cached: model=%s, camera=%s, version=%s",
                    model, new_data.get("_cached_camera_type"), current_version
                )
                
                # Migrate go2rtc settings if needed
                _migrate_go2rtc_settings(hass, entry)
        else:
            # Printer is off - update version only, keep existing cached data if available
            _LOGGER.info(
                "Printer is off, updating version only (keeping existing cached data if available)"
            )
            new_data = dict(entry.data)
            new_data["_device_info_cached"] = True
            new_data["_cached_version"] = current_version
            
            # Only set defaults if this is first-time setup (no cached model exists)
            if not new_data.get("_cached_model"):
                new_data["_cached_model"] = "K by Creality"
                new_data["_cached_has_light"] = True
                new_data["_cached_has_box_sensor"] = False
                new_data["_cached_has_box_control"] = False
                new_data["_cached_camera_type"] = "mjpeg"
            
            hass.config_entries.async_update_entry(entry, data=new_data)
            
            # Migrate go2rtc settings even when printer is off
            _migrate_go2rtc_settings(hass, entry)

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
                "integration_version": await _get_integration_version(hass),
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