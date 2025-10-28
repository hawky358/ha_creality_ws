from __future__ import annotations

from typing import Any
from datetime import timedelta
from homeassistant.helpers.event import async_track_time_interval  # type: ignore[import]

from homeassistant.components.number import NumberEntity, NumberMode

# unit compat across HA versions
try:
    from homeassistant.const import UnitOfTemperature, PERCENTAGE as UNIT_PERCENT
    UNIT_CELSIUS = UnitOfTemperature.CELSIUS
except Exception:  # older cores
    from homeassistant.const import TEMP_CELSIUS as UNIT_CELSIUS, PERCENTAGE as UNIT_PERCENT

from .const import DOMAIN
from .entity import KEntity

async def async_setup_entry(hass, entry, async_add_entities):
    coord = hass.data[DOMAIN][entry.entry_id]
    ents: list[NumberEntity] = []

    # Standard entities for all printers
    ents.append(PrintTuningPercent(coord))
    ents.append(NozzleTargetNumber(coord))
    ents.append(BedTargetNumber(coord, bed_index=0))
    
    # Box temperature control (K2 Pro/Plus only)
    has_box_control = entry.data.get("_cached_has_box_control", False)
    if coord.data.get("maxBoxTemp") and has_box_control:
        ents.append(BoxTargetNumber(coord))
    
    # Fan controls
    ents.append(_FanPctNumber(coord, "Model Fan %", "modelFanPct", "model_fan_pct", channel=0))
    ents.append(_FanPctNumber(coord, "Case Fan %", "caseFanPct", "case_fan_pct", channel=1))
    ents.append(_FanPctNumber(coord, "Side Fan %", "auxiliaryFanPct", "side_fan_pct", channel=2))

    async_add_entities(ents)


# ---------- Unified speed+flow percent ----------
class PrintTuningPercent(KEntity, NumberEntity):
    """
    One control for both speed and flow.
    Writes: setFeedratePct=value and setFlowratePct=value.
    Reads:  curFeedratePct if present; falls back to curFlowratePct.
    """
    _attr_name = "Print Tuning %"
    _attr_icon = "mdi:speedometer"
    _attr_native_unit_of_measurement = UNIT_PERCENT
    _attr_mode = NumberMode.SLIDER
    _attr_native_min_value = 1.0
    _attr_native_max_value = 1000.0
    _attr_native_step = 1.0

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, self._attr_name, "print_tuning_pct")

    @property
    def native_value(self) -> float | None:
        if self._should_zero():
            return None
        d = self.coordinator.data
        v = d.get("curFeedratePct")
        if v is None:
            v = d.get("curFlowratePct")
        try:
            return float(v) if v is not None else None
        except (TypeError, ValueError):
            return None

    async def async_set_native_value(self, value: float) -> None:
        v = int(max(self._attr_native_min_value, min(self._attr_native_max_value, round(value))))
        # Write BOTH, keep them in lockstep
        await self.coordinator.client.send_set_retry(setFeedratePct=v)
        await self.coordinator.client.send_set_retry(setFlowratePct=v)


# ---------- Temperature targets (BOX inputs) ----------
class NozzleTargetNumber(KEntity, NumberEntity):
    _attr_name = "Nozzle Target"
    _attr_icon = "mdi:thermometer"
    _attr_mode = NumberMode.BOX
    _attr_native_unit_of_measurement = UNIT_CELSIUS
    _attr_native_min_value = 0.0
    _attr_native_step = 1.0

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, self._attr_name, "nozzle_target")
        # Use cached max temperature value with fallback to live data
        max_temps = self._get_cached_max_temps()
        max_nozzle_temp = max_temps.get("max_nozzle_temp")
        self._attr_native_max_value = float(max_nozzle_temp) if max_nozzle_temp is not None else 300.0
    @property
    def native_value(self) -> float | None:
        if self._should_zero():
            return None
        v = self.coordinator.data.get("targetNozzleTemp")
        try:
            return float(v) if v is not None else None
        except (TypeError, ValueError):
            return None

    async def async_set_native_value(self, value: float) -> None:
        v = int(round(value))
        v = max(int(self._attr_native_min_value or 0), v)
        max_v = self._attr_native_max_value
        if max_v is not None:
            v = min(int(max_v), v)
        await self.coordinator.client.send_set_retry(nozzleTempControl=v)


class BedTargetNumber(KEntity, NumberEntity):
    _attr_name = "Bed Target"
    _attr_icon = "mdi:radiator"
    _attr_mode = NumberMode.BOX
    _attr_native_unit_of_measurement = UNIT_CELSIUS
    _attr_native_min_value = 0.0
    _attr_native_step = 1.0

    def __init__(self, coordinator, bed_index: int = 0) -> None:
        super().__init__(coordinator, self._attr_name, f"bed_target_{bed_index}")
        self._idx = int(bed_index)
        # Use cached max temperature value with fallback to live data
        max_temps = self._get_cached_max_temps()
        max_bed_temp = max_temps.get("max_bed_temp")
        self._attr_native_max_value = float(max_bed_temp) if max_bed_temp is not None else 100.0

    @property
    def native_value(self) -> float | None:
        if self._should_zero():
            return None
        v = self.coordinator.data.get(f"targetBedTemp{self._idx}")
        try:
            return float(v) if v is not None else None
        except (TypeError, ValueError):
            return None

    async def async_set_native_value(self, value: float) -> None:
        v = int(round(value))
        v = max(int(self._attr_native_min_value or 0), v)
        max_v = self._attr_native_max_value
        if max_v is not None:
            v = min(int(max_v), v)
        await self.coordinator.client.send_set_retry(bedTempControl={"num": self._idx, "val": v})


class BoxTargetNumber(KEntity, NumberEntity):
    _attr_name = "Box Target"
    _attr_icon = "mdi:thermometer"
    _attr_mode = NumberMode.BOX
    _attr_native_unit_of_measurement = UNIT_CELSIUS
    _attr_native_min_value = 0.0
    _attr_native_step = 1.0

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, self._attr_name, "box_target")
        # Use cached max temperature value with fallback to live data
        max_temps = self._get_cached_max_temps()
        max_box_temp = max_temps.get("max_box_temp")
        
        # Handle printers without heated chamber (maxBoxTemp is None)
        if max_box_temp is None:
            # Default to 60°C for printers with box sensor but no heated chamber
            max_box_temp = 60
        elif not isinstance(max_box_temp, (int, float)):
            # Fallback for invalid values
            max_box_temp = 60
            
        self._attr_native_max_value = float(max_box_temp)
    @property
    def native_value(self) -> float | None:
        if self._should_zero():
            return None
        v = self.coordinator.data.get("targetBoxTemp")
        try:
            return float(v) if v is not None else None
        except (TypeError, ValueError):
            return None

    async def async_set_native_value(self, value: float) -> None:
        # Chamber heater only activates when > 40°C (K2 Plus behavior)
        v = 0 if value <= 40 else int(round(value))
        v = max(int(self._attr_native_min_value or 0), v)
        max_v = self._attr_native_max_value
        if max_v is not None:
            v = min(int(max_v), v)
        await self.coordinator.client.send_set_retry(boxTempControl=v)


# ---------- Fan percent via M106 (0%→off) ----------
class _FanPctNumber(KEntity, NumberEntity):
    _attr_native_unit_of_measurement = UNIT_PERCENT
    _attr_mode = NumberMode.SLIDER
    _attr_native_min_value = 0.0
    _attr_native_max_value = 100.0
    _attr_native_step = 1.0

    def __init__(self, coordinator, name: str, read_field: str, uid: str, channel: int) -> None:
        super().__init__(coordinator, name, uid)
        self._read_field = read_field
        self._channel = int(channel)

    @property
    def native_value(self) -> float | None:
        if self._should_zero():
            return None
        v = self.coordinator.data.get(self._read_field)
        try:
            return float(v) if v is not None else None
        except (TypeError, ValueError):
            return None

    async def async_set_native_value(self, value: float) -> None:
        pct = max(0, min(100, int(round(value))))
        s_val = int(round(255 * (pct / 100.0)))
        cmd = f"M106 P{self._channel} S{s_val}"  # 0 → fan off
        await self.coordinator.client.send_set_retry(gcodeCmd=cmd)
