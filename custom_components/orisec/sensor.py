"""Sensor entities for Orisec ControlPlus2 panel information."""

from __future__ import annotations

import logging

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, SOS_PANEL_AC_ON, SOS_TROUBLE, SOS_CALL_ENGINEER
from .coordinator import OrisecCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: OrisecCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([OrisecPanelInfoSensor(coordinator, entry)])


class OrisecPanelInfoSensor(CoordinatorEntity[OrisecCoordinator], SensorEntity):

    _attr_has_entity_name = True
    _attr_name = "Panel Info"
    _attr_icon = "mdi:shield-home"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: OrisecCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_panel_status"

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
    def native_value(self) -> str:
        return "online" if self.coordinator.connected else "offline"

    @property
    def extra_state_attributes(self):
        sos = self.coordinator.sys_output_state
        attrs = {
            "serial": self.coordinator.serial,
            "panel_type": self.coordinator.panel_type,
            "panel_version": self.coordinator.panel_version,
            "host": self.coordinator.host,
            "max_zones": self.coordinator.max_zones,
            "max_areas": self.coordinator.max_areas,
            "max_remote_outputs": self.coordinator.max_rem_outputs,
            "part_arm_mask": f"{self.coordinator.part_arm_mask:03b}",
            "ac_power": bool(sos[SOS_PANEL_AC_ON] & 0xFF) if sos else False,
            "trouble": bool(sos[SOS_TROUBLE] & 0xFF) if sos else False,
            "engineer_required": bool(sos[SOS_CALL_ENGINEER] & 0xFF) if sos else False,
        }

        if self.coordinator.area_names:
            for i, name in enumerate(self.coordinator.area_names):
                if name:
                    state = self.coordinator.get_alarm_state_for_area(i)
                    attrs[f"area_{i + 1}_name"] = name
                    attrs[f"area_{i + 1}_state"] = state

        if self.coordinator.part_arm_names:
            attrs["part_arm_names"] = [
                n for n in self.coordinator.part_arm_names if n
            ]

        return attrs
