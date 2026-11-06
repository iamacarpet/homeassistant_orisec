"""Diagnostics download for the Orisec ControlPlus2 integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_PASSWORD, DOMAIN
from .coordinator import OrisecCoordinator

TO_REDACT = {CONF_PASSWORD}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    coordinator: OrisecCoordinator = hass.data[DOMAIN][entry.entry_id]
    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "panel": {
            "panel_type": coordinator.panel_type,
            "panel_version": coordinator.panel_version,
            "max_zones": coordinator.max_zones,
            "max_areas": coordinator.max_areas,
            "max_remote_outputs": coordinator.max_rem_outputs,
            "user_area": f"0x{coordinator.user_area:X}",
            "areas": [
                coordinator.get_alarm_state_for_area(i)
                for i in range(coordinator.max_areas)
            ],
        },
        "connection": coordinator.diagnostics(),
    }
