"""Creality K1C Card Registration."""
import logging
from pathlib import Path

# --- NEW IMPORT ---
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
        
        # --- THIS IS THE CORRECTED CODE BLOCK ---
        try:
            # Use the correct async method which takes a list of StaticPathConfig
            await self.hass.http.async_register_static_paths([
                StaticPathConfig(URL_BASE, str(frontend_path), cache_headers=False)
            ])
            _LOGGER.debug("Registered static path %s for K1C card", URL_BASE)
        except ValueError:
            # Path is already registered, which is fine
            _LOGGER.debug("Static path %s already registered", URL_BASE)

        # The rest of the registration logic is correct
        lovelace: LovelaceData | None = self.hass.data.get("lovelace")
        if lovelace is None or lovelace.mode != "storage":
            return

        resources = lovelace.resources
        if not await resources.async_get_info(CARD_URL):
            _LOGGER.info("Registering K1C printer card with Lovelace")
            await resources.async_create_item({
                "res_type": "module",
                "url": CARD_URL,
            })

    async def async_unregister(self):
        """Unregister the card from Lovelace."""
        lovelace: LovelaceData | None = self.hass.data.get("lovelace")
        if lovelace is None or lovelace.mode != "storage":
            return

        resources = lovelace.resources
        if await resources.async_get_info(CARD_URL):
            _LOGGER.info("Unregistering K1C printer card from Lovelace")
            resource_id = [item["id"] for item in resources.async_items() if item["url"] == CARD_URL][0]
            await resources.async_delete_item(resource_id)