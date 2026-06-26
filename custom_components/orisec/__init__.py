"""The Orisec ControlPlus2 integration."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from homeassistant.components import frontend
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.update_coordinator import UpdateFailed

from .const import DOMAIN, PLATFORMS, CONF_PANEL_IP, CONF_PANEL_PORT, CONF_PASSWORD
from .coordinator import OrisecCoordinator

_LOGGER = logging.getLogger(__name__)

_CARD_URL = "/orisec_panel/orisec-alarm-panel-card.js"
_WWW_DIR = Path(__file__).parent / "www"


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    # Register the custom Lovelace card once per HA instance start.
    if not hass.data.get(f"{DOMAIN}_card_loaded"):
        await hass.http.async_register_static_paths(
            [StaticPathConfig("/orisec_panel", str(_WWW_DIR), cache_headers=False)]
        )
        frontend.add_extra_js_url(hass, _CARD_URL)
        hass.data[f"{DOMAIN}_card_loaded"] = True

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
