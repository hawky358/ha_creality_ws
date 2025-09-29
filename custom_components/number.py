from __future__ import annotations

from typing import Any

from homeassistant.components.number import NumberEntity, NumberMode

# unit compat across HA versions
try:
    from homeassistant.const import UnitOfTemperature, PERCENTAGE as UNIT_PERCENT
    UNIT_CELSIUS = UnitOfTemperature.CELSIUS
except Exception:  # older cores
    from homeassistant.const import TEMP_CELSIUS as UNIT_CELSIUS, PERCENTAGE as UNIT_PERCENT

from .const import DOMAIN
from .entity import K1CEntity


async def async_setup_entry(hass, entry, async_add_entities):
    coord = hass.data[DOMAIN][entry.entry_id]
    ents: list[NumberEntity] = []

    # ---- Unified print tuning: writes BOTH speed and flow together ----
    ents.append(PrintTuningPercent(coord))

    # ---- Target temperatures (number input boxes) ----
    ents.append(NozzleTargetNumber(coord))
    ents.append(BedTargetNumber(coord, bed_index=0))

    # ---- Fan percentages via M106 Pn Sxxx (no switches) ----
    ents.append(_FanPctNumber(coord, "Model Fan %", "modelFanPct", "model_fan_pct", channel=0))
    ents.append(_FanPctNumber(coord, "Case Fan %", "caseFanPct", "case_fan_pct", channel=1))
    ents.append(_FanPctNumber(coord, "Side Fan %", "auxiliaryFanPct", "side_fan_pct", channel=2))

    async_add_entities(ents)


# ---------- Unified speed+flow percent ----------
class PrintTuningPercent(K1CEntity, NumberEntity):
    """
    One control for both speed and flow.
    Writes: setFeedratePct=value and setFlowratePct=value.
    Reads:  curFeedratePct if present; falls back to curFlowratePct.
    """
    _attr_name = "Print Tuning %"
    _attr_icon = "mdi:speedometer"
    _attr_native_unit_of_measurement = UNIT_PERCENT
    _attr_mode = NumberMode.SLIDER  # keep as slider for tuning; change to BOX if you prefer
    _attr_native_min_value = 1.0
    _attr_native_max_value = 1000.0  # you tested 666%; leave room for speed benches
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
class NozzleTargetNumber(K1CEntity, NumberEntity):
    _attr_name = "Nozzle Target"
    _attr_icon = "mdi:thermometer"
    _attr_mode = NumberMode.BOX
    _attr_native_unit_of_measurement = UNIT_CELSIUS
    _attr_native_min_value = 0.0
    _attr_native_max_value = 300.0
    _attr_native_step = 1.0

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, self._attr_name, "nozzle_target")

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
        v = int(max(0, min(300, round(value))))
        await self.coordinator.client.send_set_retry(nozzleTempControl=v)


class BedTargetNumber(K1CEntity, NumberEntity):
    _attr_name = "Bed Target"
    _attr_icon = "mdi:radiator"
    _attr_mode = NumberMode.BOX
    _attr_native_unit_of_measurement = UNIT_CELSIUS
    _attr_native_min_value = 0.0
    _attr_native_max_value = 100.0
    _attr_native_step = 1.0

    def __init__(self, coordinator, bed_index: int = 0) -> None:
        super().__init__(coordinator, self._attr_name, f"bed_target_{bed_index}")
        self._idx = int(bed_index)

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
        v = int(max(0, min(100, round(value))))
        await self.coordinator.client.send_set_retry(bedTempControl={"num": self._idx, "val": v})


# ---------- Fan percent via M106 (0%→off) ----------
class _FanPctNumber(K1CEntity, NumberEntity):
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
