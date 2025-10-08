from __future__ import annotations
from homeassistant.helpers.entity import DeviceInfo #type: ignore[import]
from homeassistant.helpers.update_coordinator import CoordinatorEntity #type: ignore[import]

from .const import DOMAIN, MFR, MODEL
from .utils import parse_model_version


def _parse_model_version(s: str | None) -> tuple[str | None, str | None]:
    """
    Accept strings like:
      "printer hw ver:;printer sw ver:;DWIN hw ver:CR4CU220812S11;DWIN sw ver:1.3.3.46;"
    Extract the most meaningful HW/SW values and drop empties.
    """
    if not s or not isinstance(s, str):
        return (None, None)

    parts = {}
    for seg in s.split(";"):
        seg = seg.strip()
        if not seg or ":" not in seg:
            continue
        k, v = seg.split(":", 1)
        k = k.strip().lower()
        v = v.strip() or None
        parts[k] = v

    # Preference order: printer* first, then DWIN*
    hw = parts.get("printer hw ver") or parts.get("dwin hw ver")
    sw = parts.get("printer sw ver") or parts.get("dwin sw ver")
    # Prefix DWIN if that's what we ended up using
    if hw and hw == parts.get("dwin hw ver"):
        hw = f"DWIN {hw}"
    if sw and sw == parts.get("dwin sw ver"):
        sw = f"DWIN {sw}"
    return (hw, sw)


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

    @property
    def device_info(self) -> DeviceInfo:
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
