from __future__ import annotations
from homeassistant.helpers.entity import DeviceInfo #type: ignore[import]
from homeassistant.helpers.update_coordinator import CoordinatorEntity #type: ignore[import]

from .const import DOMAIN, MFR, MODEL
from .utils import parse_model_version


class KEntity(CoordinatorEntity):
    """Base entity for Creality K-series over WebSocket."""

    _attr_has_entity_name = True

    def __init__(self, coordinator, name: str, unique_id: str):
        super().__init__(coordinator)
        self._attr_name = name
        self._attr_unique_id = f"{coordinator.client._host}-{unique_id}"
        self._host = coordinator.client._host

    @property
    def available(self) -> bool:
        # Keep entities available so we can surface zeroed values when off/unknown
        return True

    # Helper used by sensors to decide zeroing
    def _should_zero(self) -> bool:
        """
        Helper to determine if an entity should show a zero/off/none value.
        """
        coord = self.coordinator
        # Returns True if connection is lost OR if the power switch is off.
        return (not coord.available) or coord.power_is_off()
    
    def _get_cached_device_info(self) -> dict | None:
        """
        Get cached device info from config entry (model, hostname, modelVersion).
        Returns None if not available.
        """
        try:
            entry_id = getattr(self.coordinator, '_config_entry_id', None)
            if entry_id:
                entry_obj = self.coordinator.hass.config_entries.async_get_entry(entry_id)
                if entry_obj and entry_obj.data.get("_device_info_cached"):
                    return {
                        "model": entry_obj.data.get("_cached_model"),
                        "hostname": entry_obj.data.get("_cached_hostname"),
                        "modelVersion": entry_obj.data.get("_cached_model_version"),
                    }
        except Exception:
            pass
        return None

    @property
    def device_info(self) -> DeviceInfo:
        # First try to get cached device info from entry
        cached_info = self._get_cached_device_info()
        if cached_info and cached_info.get("model"):
            hw_ver, sw_ver = parse_model_version(cached_info.get("modelVersion"))
            return DeviceInfo(
                identifiers={(DOMAIN, self._host)},
                manufacturer=MFR,
                model=cached_info.get("model"),
                name=cached_info.get("hostname") or f"{cached_info.get('model')} (Creality)",
                configuration_url=f"http://{self._host}/",
                hw_version=hw_ver,
                sw_version=sw_ver,
            )
        
        # Fallback to current telemetry (for backwards compatibility)
        d = self.coordinator.data or {}
        model = d.get("model") or MODEL
        hostname = d.get("hostname")

        # Clean firmware/hardware versions
        hw_ver, sw_ver = parse_model_version(d.get("modelVersion"))

        return DeviceInfo(
            identifiers={(DOMAIN, self._host)},
            manufacturer=MFR,
            model=model,
            name=hostname or f"{model} (Creality)",
            configuration_url=f"http://{self._host}/",
            hw_version=hw_ver,
            sw_version=sw_ver,
        )
