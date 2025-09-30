"""Creality K1C Card Registration."""
import logging
from pathlib import Path

from homeassistant.components.http import StaticPathConfig
from homeassistant.components.lovelace import LovelaceData
from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

URL_BASE = "/ha_creality_ws_local"
CARD_NAME = "k1c-printer-card.js"
CARD_URL = f"{URL_BASE}/{CARD_NAME}"

class CrealityCardRegistration:
    """Handles the registration of the K1C printer card."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass

    async def async_register(self):
        """Register the card with Lovelace."""
        
        frontend_path = Path(__file__).parent / "frontend"
        
        try:
            await self.hass.http.async_register_static_paths([
                StaticPathConfig(URL_BASE, str(frontend_path), cache_headers=False)
            ])
            _LOGGER.debug("Registered static path %s for K1C card", URL_BASE)
        except ValueError:
            _LOGGER.debug("Static path %s already registered", URL_BASE)

        lovelace: LovelaceData | None = self.hass.data.get("lovelace")
        if lovelace is None or lovelace.mode != "storage":
            return

        # --- THIS IS THE CORRECTED LOGIC ---
        # Get all registered resources and check if our card's URL is present.
        resources = lovelace.resources.async_items()
        card_registered = any(resource["url"] == CARD_URL for resource in resources)

        if not card_registered:
            _LOGGER.info("Registering K1C printer card with Lovelace: %s", CARD_URL)
            await lovelace.resources.async_create_item({
                "res_type": "module",
                "url": CARD_URL,
            })
        else:
            _LOGGER.debug("K1C printer card is already registered.")


    async def async_unregister(self):
        """Unregister the card from Lovelace."""
        lovelace: LovelaceData | None = self.hass.data.get("lovelace")
        if lovelace is None or lovelace.mode != "storage":
            return

        # --- THIS IS THE CORRECTED UNREGISTER LOGIC ---
        # Find the specific resource ID to delete.
        resource_id_to_delete = None
        for resource in lovelace.resources.async_items():
            if resource["url"] == CARD_URL:
                resource_id_to_delete = resource["id"]
                break
        
        if resource_id_to_delete:
            _LOGGER.info("Unregistering K1C printer card from Lovelace")
            await lovelace.resources.async_delete_item(resource_id_to_delete)