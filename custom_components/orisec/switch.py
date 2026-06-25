"""Switch entities for Orisec ControlPlus2 remote outputs."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import OrisecCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: OrisecCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SwitchEntity] = []

    for output_idx in range(coordinator.max_rem_outputs):
        name = (
            coordinator.rem_output_names[output_idx]
            if output_idx < len(coordinator.rem_output_names)
            and coordinator.rem_output_names[output_idx]
            else f"Output {output_idx + 1}"
        )
        entities.append(
            OrisecOutputSwitch(coordinator, entry, output_idx, name)
        )

    async_add_entities(entities)


class OrisecOutputSwitch(CoordinatorEntity[OrisecCoordinator], SwitchEntity):

    _attr_has_entity_name = True
    _attr_entity_registry_enabled_default = False

    def __init__(
        self,
        coordinator: OrisecCoordinator,
        entry: ConfigEntry,
        output_idx: int,
        name: str,
    ) -> None:
        super().__init__(coordinator)
        self._output_idx = output_idx
        self._attr_name = name
        self._attr_unique_id = f"{entry.entry_id}_output_{output_idx + 1}"

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self.coordinator.serial or self.coordinator.host)},
            "name": f"Orisec {self.coordinator.panel_type or 'Panel'}",
            "manufacturer": "Orisec",
            "model": self.coordinator.panel_type,
            "sw_version": self.coordinator.panel_version,
        }

    @property
    def is_on(self) -> bool:
        return self.coordinator.get_output_state(self._output_idx)

    async def async_turn_on(self, **kwargs: Any) -> None:
        if not self.is_on:
            await self.coordinator.async_toggle_output(self._output_idx)

    async def async_turn_off(self, **kwargs: Any) -> None:
        if self.is_on:
            await self.coordinator.async_toggle_output(self._output_idx)
