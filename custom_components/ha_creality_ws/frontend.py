import logging
import shutil
from pathlib import Path
from homeassistant.components.lovelace import LovelaceData
from homeassistant.core import HomeAssistant
from asyncio import sleep
from typing import Any

_LOGGER = logging.getLogger(__name__)

LOCAL_SUBDIR = "ha_creality_ws"
CARD_NAME = "k_printer_card.js"
BASE_URL = f"/local/{LOCAL_SUBDIR}/{CARD_NAME}"  # served from /config/www/...

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

        def _sync_copy():
            dst.parent.mkdir(parents=True, exist_ok=True)
            # copy if missing or outdated
            src_mtime = src.stat().st_mtime_ns
            try:
                dst_mtime = dst.stat().st_mtime_ns
            except FileNotFoundError:
                dst_mtime = -1
            if dst_mtime < src_mtime:
                shutil.copy2(src, dst)
                return True
            return False

        try:
            changed = await self.hass.async_add_executor_job(_sync_copy)
            if changed:
                _LOGGER.info("Deployed K card to %s", dst)
            else:
                _LOGGER.debug("K card already up-to-date at %s", dst)
        except Exception as exc:
            _LOGGER.warning("Failed to deploy K card to %s: %s", dst, exc)

    async def async_register(self) -> None:
        """Deploy card and ensure Lovelace resource exists (storage mode), with cache-busting."""
        await self._deploy_card()

        lovelace: LovelaceData | None = self.hass.data.get("lovelace")
        if lovelace is None or lovelace.mode != "storage":
            # YAML mode: cannot programmatically add resources; user must add BASE_URL manually.
            _LOGGER.debug("Lovelace not in storage mode; skipping resource auto-register")
            return

        # Build versioned URL based on the source file mtime to bust caches
        try:
            src = self._src_path()
            ver_ns = await self.hass.async_add_executor_job(lambda: src.stat().st_mtime_ns)
            ver = str(ver_ns)
        except Exception:
            ver = "1"
        versioned_url = f"{BASE_URL}?v={ver}"

        # Accessing lovelace.resources too early during startup can trigger a
        # race in Home Assistant's storage layer that results in wiping
        # existing .storage/lovelace_resources. To be defensive, retry a few
        # times with a short backoff if the collection appears empty or
        # inconsistent.
        resources: list[dict[str, Any]] | None = None
        for _ in range(5):
            try:
                resources = lovelace.resources.async_items()
            except Exception:
                resources = None
            if resources:
                break
            await sleep(0.25)
        if not resources:
            # Give up gracefully; avoid creating resources when storage
            # doesn't look ready.
            _LOGGER.warning("Lovelace resources unavailable after retries; skipping auto-register")
            return
        # Try to find an existing resource that points to this file (with or without query string)
        existing = None
        for r in resources:
            url = (r.get("url") or "").strip()
            if url == versioned_url or url.split("?")[0] == BASE_URL:
                existing = r
                break

        if not existing:
            _LOGGER.info("Registering Lovelace resource for K card: %s", versioned_url)
            # creation can still raise if storage is not ready; guard with try
            try:
                await lovelace.resources.async_create_item({"res_type": "module", "url": versioned_url})
            except Exception as exc:
                _LOGGER.warning("Failed to create Lovelace resource: %s", exc)
        else:
            rid = existing.get("id")
            if existing.get("url") != versioned_url and rid is not None:
                _LOGGER.info("Updating Lovelace resource URL for K card to %s", versioned_url)
                try:
                    await lovelace.resources.async_update_item(rid, {"res_type": "module", "url": versioned_url})
                except Exception:
                    # Fallback: delete and recreate
                    try:
                        await lovelace.resources.async_delete_item(rid)
                    except Exception:
                        pass
                    try:
                        await lovelace.resources.async_create_item({"res_type": "module", "url": versioned_url})
                    except Exception as exc:
                        _LOGGER.warning("Failed to recreate Lovelace resource: %s", exc)

    async def async_unregister(self) -> None:
        """Remove Lovelace resource (keep the file under /config/www)."""
        lovelace: LovelaceData | None = self.hass.data.get("lovelace")
        if lovelace is None or lovelace.mode != "storage":
            return

        rid = None
        for r in lovelace.resources.async_items():
            url = (r.get("url") or "").strip()
            if url.split("?")[0] == BASE_URL:
                rid = r.get("id")
                break
        if rid:
            _LOGGER.info("Removing Lovelace resource for K card")
            await lovelace.resources.async_delete_item(rid)
