from __future__ import annotations

from homeassistant.components.switch import SwitchEntity

from .entity import KEntity
from .const import DOMAIN

# Only keep switches that make sense as binary (e.g., light).
MAP = {
    "light": ("Light", "lightSw"),
    # Fan switches removed; use % numbers instead.
}


async def async_setup_entry(hass, entry, async_add_entities):
    coord = hass.data[DOMAIN][entry.entry_id]
    
    # Model detection logic
    model = (coord.data or {}).get("model") or ""
    model_l = str(model).lower()
    
    is_k1_family = "k1" in model_l
    is_k1_se = is_k1_family and "se" in model_l
    is_k1_max = is_k1_family and "max" in model_l
    is_k2_family = "k2" in model_l
    is_ender_v3_family = "ender" in model_l and "v3" in model_l
    is_creality_hi = "hi" in model_l
    
    # Models without light: K1 SE, Ender 3 V3 family
    has_light = not (is_k1_se or is_ender_v3_family)
    
    ents = []
    for key, (name, field) in MAP.items():
        # Skip light switch for models without light
        if key == "light" and not has_light:
            continue
        ents.append(KSimpleSwitch(coord, name, field, key))
    
    async_add_entities(ents)


class KSimpleSwitch(KEntity, SwitchEntity):
    _attr_icon = "mdi:toggle-switch"

    def __init__(self, coordinator, name: str, field: str, unique_id: str):
        super().__init__(coordinator, name, unique_id)
        self._field = field

    @property
    def is_on(self) -> bool:
        if self._should_zero():
            return False
        val = self.coordinator.data.get(self._field)
        return bool(val) if val is not None else False

    async def async_turn_on(self, **kwargs):
        await self.coordinator.client.send_set_retry(**{self._field: 1})

    async def async_turn_off(self, **kwargs):
        await self.coordinator.client.send_set_retry(**{self._field: 0})
