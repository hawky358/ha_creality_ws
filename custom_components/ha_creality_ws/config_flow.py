from __future__ import annotations
import asyncio
import logging
from typing import Any, Optional
from .utils import extract_host_from_zeroconf as util_extract_host_from_zeroconf
import voluptuous as vol
from homeassistant import config_entries #type: ignore[import]
from homeassistant.data_entry_flow import FlowResult #type: ignore[import]
from homeassistant.helpers import config_validation as cv, selector #type: ignore[import]
from .const import DOMAIN, CONF_HOST, CONF_NAME, DEFAULT_NAME, WS_PORT, CONF_POWER_SWITCH

_LOGGER = logging.getLogger(__name__)

async def _probe_tcp(host: str, port: int, timeout: float = 2.5) -> bool:
    try:
        fut = asyncio.open_connection(host, port)
        reader, writer = await asyncio.wait_for(fut, timeout=timeout)
        writer.close()
        await writer.wait_closed()
        return True
    except Exception:
        return False


def _extract_host_from_zeroconf(info: Any) -> Optional[str]:
    # Use shared helper for testability
    return util_extract_host_from_zeroconf(info)


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 3

    @staticmethod
    @config_entries.HANDLERS.register("options")
    def async_get_options_flow(config_entry: config_entries.ConfigEntry):
        return OptionsFlowHandler(config_entry)

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            await self.async_set_unique_id(host)
            self._abort_if_unique_id_configured()

            if not await _probe_tcp(host, WS_PORT):
                errors["base"] = "cannot_connect"
            else:
                title = user_input.get(CONF_NAME) or f"{DEFAULT_NAME} ({host})"
                return self.async_create_entry(title=title, data={CONF_HOST: host})

        schema = vol.Schema({
            vol.Required(CONF_HOST): str,
            vol.Optional(CONF_NAME, default=DEFAULT_NAME): str,
        })
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_zeroconf(self, discovery_info: Any) -> FlowResult:
        host = _extract_host_from_zeroconf(discovery_info)
        if not host:
            return self.async_abort(reason="cannot_connect")

        if not await _probe_tcp(host, WS_PORT):
            return self.async_abort(reason="not_K")

        await self.async_set_unique_id(host)
        self._abort_if_unique_id_configured()

        title = f"{DEFAULT_NAME} ({host})"
        return self.async_create_entry(title=title, data={CONF_HOST: host})


# --------- Options Flow ---------
class OptionsFlowHandler(config_entries.OptionsFlow):
    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self.config_entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        schema = vol.Schema({
            vol.Optional(
                CONF_POWER_SWITCH,
                default=self.config_entry.options.get(CONF_POWER_SWITCH, "")
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="switch")
            ),
        })
        return self.async_show_form(step_id="init", data_schema=schema)