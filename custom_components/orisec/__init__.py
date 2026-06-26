"""The Orisec ControlPlus2 integration."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import voluptuous as vol

from homeassistant.components import frontend, websocket_api
from homeassistant.components.http import StaticPathConfig
from homeassistant.components.panel_custom import async_register_panel
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.update_coordinator import UpdateFailed

from .const import DOMAIN, PLATFORMS, CONF_PANEL_IP, CONF_PANEL_PORT, CONF_PASSWORD
from .coordinator import OrisecCoordinator

_LOGGER = logging.getLogger(__name__)

_CARD_URL = "/orisec_panel/orisec-alarm-panel-card.js"
_KEYPAD_CARD_URL = "/orisec_panel/orisec-keypad-card.js"
_WWW_DIR = Path(__file__).parent / "www"


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if not hass.data.get(f"{DOMAIN}_card_loaded"):
        await hass.http.async_register_static_paths(
            [StaticPathConfig("/orisec_panel", str(_WWW_DIR), cache_headers=False)]
        )
        frontend.add_extra_js_url(hass, _CARD_URL)
        frontend.add_extra_js_url(hass, _KEYPAD_CARD_URL)
        hass.data[f"{DOMAIN}_card_loaded"] = True

    if not hass.data.get(f"{DOMAIN}_panel_registered"):
        await async_register_panel(
            hass,
            frontend_url_path="orisec",
            webcomponent_name="orisec-panel",
            sidebar_title="Orisec",
            sidebar_icon="mdi:shield-home",
            module_url="/orisec_panel/orisec-panel.js",
            embed_iframe=False,
            require_admin=False,
        )
        hass.data[f"{DOMAIN}_panel_registered"] = True

    if not hass.data.get(f"{DOMAIN}_ws_registered"):
        websocket_api.async_register_command(hass, ws_handle_keypad_subscribe)
        websocket_api.async_register_command(hass, ws_handle_keypad_press)
        websocket_api.async_register_command(hass, ws_handle_keypad_entries)
        hass.data[f"{DOMAIN}_ws_registered"] = True

    coordinator = OrisecCoordinator(
        hass,
        host=entry.data[CONF_PANEL_IP],
        port=entry.data[CONF_PANEL_PORT],
        password=entry.data[CONF_PASSWORD],
    )

    try:
        await coordinator.async_setup()
    except (ConnectionError, OSError, asyncio.TimeoutError, UpdateFailed) as err:
        raise ConfigEntryNotReady(f"Cannot connect to Orisec panel: {err}") from err

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        coordinator: OrisecCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_shutdown()

    return unload_ok


def _get_coordinator(
    hass: HomeAssistant, entry_id: str | None
) -> OrisecCoordinator | None:
    entries = hass.data.get(DOMAIN, {})
    if entry_id:
        return entries.get(entry_id)
    if len(entries) == 1:
        return next(iter(entries.values()))
    return None


@websocket_api.websocket_command(
    {
        vol.Required("type"): "orisec/keypad/entries",
    }
)
@websocket_api.async_response
async def ws_handle_keypad_entries(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
) -> None:
    entries = hass.data.get(DOMAIN, {})
    result = []
    for eid, coord in entries.items():
        result.append({
            "entry_id": eid,
            "panel_type": coord.panel_type,
            "serial": coord.serial,
        })
    connection.send_result(msg["id"], result)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "orisec/keypad/subscribe",
        vol.Optional("entry_id"): str,
    }
)
@websocket_api.async_response
async def ws_handle_keypad_subscribe(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
) -> None:
    coordinator = _get_coordinator(hass, msg.get("entry_id"))
    if coordinator is None:
        connection.send_error(msg["id"], "not_found", "Orisec entry not found")
        return

    def send_lcd_update(state: dict) -> None:
        connection.send_message(
            websocket_api.event_message(msg["id"], state)
        )

    unsubscribe = coordinator.keypad_subscribe(send_lcd_update)
    connection.subscriptions[msg["id"]] = unsubscribe
    connection.send_result(msg["id"])


@websocket_api.websocket_command(
    {
        vol.Required("type"): "orisec/keypad/press",
        vol.Optional("entry_id"): str,
        vol.Required("char"): str,
    }
)
@websocket_api.async_response
async def ws_handle_keypad_press(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
) -> None:
    coordinator = _get_coordinator(hass, msg.get("entry_id"))
    if coordinator is None:
        connection.send_error(msg["id"], "not_found", "Orisec entry not found")
        return

    try:
        await coordinator.async_send_keypad_char(msg["char"])
        connection.send_result(msg["id"])
    except (ConnectionError, ValueError) as err:
        connection.send_error(msg["id"], "error", str(err))
