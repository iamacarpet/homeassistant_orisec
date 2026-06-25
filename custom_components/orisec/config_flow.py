"""Config flow for Orisec ControlPlus2 integration."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_PASSWORD

from .const import DOMAIN, DEFAULT_PORT, CONF_PANEL_IP, CONF_PANEL_PORT, CONF_PASSWORD as ORISEC_CONF_PASSWORD
from .protocol import OrisecConnection

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
        vol.Required(CONF_PASSWORD): str,
    }
)


class OrisecConfigFlow(ConfigFlow, domain=DOMAIN):

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST]
            port = user_input[CONF_PORT]
            password = user_input[CONF_PASSWORD]

            conn = OrisecConnection(host, port)
            try:
                await conn.connect()
                result = await conn.login(password)

                if result.error == 3:
                    errors["base"] = "invalid_auth"
                elif not result.logged_in:
                    errors["base"] = "cannot_connect"
                else:
                    unique_id = result.serial or f"{host}:{port}"
                    await self.async_set_unique_id(unique_id)
                    self._abort_if_unique_id_configured()

                    title = f"Orisec {result.panel_type or 'Panel'}"
                    if result.serial:
                        title += f" ({result.serial})"

                    return self.async_create_entry(
                        title=title,
                        data={
                            CONF_PANEL_IP: host,
                            CONF_PANEL_PORT: port,
                            CONF_PASSWORD: password,
                        },
                    )
            except (ConnectionError, OSError, asyncio.TimeoutError):
                errors["base"] = "cannot_connect"
            finally:
                await conn.disconnect()

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )
