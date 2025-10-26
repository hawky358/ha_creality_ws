from __future__ import annotations

from homeassistant.components.switch import SwitchEntity

from .entity import KEntity
from .const import DOMAIN
from .utils import ModelDetection
# Only keep switches that make sense as binary (e.g., light).
MAP = {
    "light": ("Light", "lightSw"),
    # Fan switches removed; use % numbers instead.
}

async def async_setup_entry(hass, entry, async_add_entities):
    coord = hass.data[DOMAIN][entry.entry_id]
    
    # Model detection logic
    printermodel = ModelDetection(coord.data)
    
    ents = []
    for key, (name, field) in MAP.items():
        # Skip light switch for models without light
        if key == "light" and not printermodel.has_light:
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