# custom_components/ha_creality_ws/frontend.py

"""Creality K Card registration and deploy to /local."""
import logging
import shutil
from pathlib import Path
from homeassistant.components.lovelace import LovelaceData
from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

LOCAL_SUBDIR = "ha_creality_ws"
CARD_NAME = "k_printer_card.js"
LOCAL_URL = f"/local/{LOCAL_SUBDIR}/{CARD_NAME}"  # served from /config/www/...

class CrealityCardRegistration:
    """Deploys k_printer_card.js to /config/www and registers Lovelace resource."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass

    def _src_path(self) -> Path:
        # card bundled inside the integration
        return Path(__file__).parent / "frontend" / CARD_NAME

    def _dst_path(self) -> Path:
        # target under /config/www/ha_creality_ws/k_printer_card.js
        return Path(self.hass.config.path("www")) / LOCAL_SUBDIR / CARD_NAME

    async def _deploy_card(self) -> None:
        src = self._src_path()
        dst = self._dst_path()
        dst.parent.mkdir(parents=True, exist_ok=True)

        try:
            # copy if missing or outdated
            need_copy = (not dst.exists()) or (src.stat().st_mtime_ns > dst.stat().st_mtime_ns)
            if need_copy:
                shutil.copy2(src, dst)
                _LOGGER.info("Deployed K card to %s", dst)
            else:
                _LOGGER.debug("K card already up-to-date at %s", dst)
        except Exception as exc:
            _LOGGER.warning("Failed to deploy K card to %s: %s", dst, exc)

    async def async_register(self) -> None:
        """Deploy card and ensure Lovelace resource exists (storage mode)."""
        await self._deploy_card()

        lovelace: LovelaceData | None = self.hass.data.get("lovelace")
        if lovelace is None or lovelace.mode != "storage":
            # YAML mode: cannot programmatically add resources; user must add LOCAL_URL manually.
            _LOGGER.debug("Lovelace not in storage mode; skipping resource auto-register")
            return

        resources = lovelace.resources.async_items()
        if not any((r.get("url") == LOCAL_URL) for r in resources):
            _LOGGER.info("Registering Lovelace resource for K card: %s", LOCAL_URL)
            await lovelace.resources.async_create_item({"res_type": "module", "url": LOCAL_URL})
        else:
            _LOGGER.debug("Lovelace resource already present: %s", LOCAL_URL)

    async def async_unregister(self) -> None:
        """Remove Lovelace resource (keep the file under /config/www)."""
        lovelace: LovelaceData | None = self.hass.data.get("lovelace")
        if lovelace is None or lovelace.mode != "storage":
            return

        rid = None
        for r in lovelace.resources.async_items():
            if r.get("url") == LOCAL_URL:
                rid = r.get("id")
                break
        if rid:
            _LOGGER.info("Removing Lovelace resource for K card")
            await lovelace.resources.async_delete_item(rid)
