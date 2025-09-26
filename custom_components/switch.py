from __future__ import annotations

from homeassistant.components.switch import SwitchEntity

from .entity import K1CEntity
from .const import DOMAIN

# Only keep switches that make sense as binary (e.g., light).
MAP = {
    "light": ("Light", "lightSw"),
    # Fan switches removed; use % numbers instead.
}


async def async_setup_entry(hass, entry, async_add_entities):
    coord = hass.data[DOMAIN][entry.entry_id]
    ents = [K1CSimpleSwitch(coord, name, field, key) for key, (name, field) in MAP.items()]
    async_add_entities(ents)


class K1CSimpleSwitch(K1CEntity, SwitchEntity):
    _attr_icon = "mdi:toggle-switch"

    def __init__(self, coordinator, name: str, field: str, unique_id: str):
        super().__init__(coordinator, name, unique_id)
        self._field = field

    @property
    def is_on(self) -> bool:
        val = self.coordinator.data.get(self._field)
        return bool(val) if val is not None else False

    async def async_turn_on(self, **kwargs):
        await self.coordinator.client.send_set_retry(**{self._field: 1})

    async def async_turn_off(self, **kwargs):
        await self.coordinator.client.send_set_retry(**{self._field: 0})
