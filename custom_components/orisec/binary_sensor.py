"""Binary sensor entities for Orisec ControlPlus2 zones."""

from __future__ import annotations

import logging

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, ZONE_TYPE_NOT_USED, ZONE_TYPE_NAMES, ZONE_TYPE_TO_DEVICE_CLASS
from .coordinator import OrisecCoordinator

_LOGGER = logging.getLogger(__name__)

_DEVICE_CLASS_MAP: dict[str, BinarySensorDeviceClass] = {
    "motion": BinarySensorDeviceClass.MOTION,
    "opening": BinarySensorDeviceClass.OPENING,
    "door": BinarySensorDeviceClass.DOOR,
    "smoke": BinarySensorDeviceClass.SMOKE,
    "safety": BinarySensorDeviceClass.SAFETY,
    "problem": BinarySensorDeviceClass.PROBLEM,
    "tamper": BinarySensorDeviceClass.TAMPER,
    "moisture": BinarySensorDeviceClass.MOISTURE,
    "gas": BinarySensorDeviceClass.GAS,
    "occupancy": BinarySensorDeviceClass.OCCUPANCY,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: OrisecCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[BinarySensorEntity] = []

    for zone_idx in range(coordinator.max_zones):
        zone_type = coordinator.get_zone_type(zone_idx)
        if zone_type == ZONE_TYPE_NOT_USED:
            continue

        zone_name = coordinator.get_zone_name(zone_idx)
        if not zone_name:
            continue

        entities.append(
            OrisecZoneSensor(coordinator, entry, zone_idx, zone_type, zone_name)
        )
        entities.append(
            OrisecZoneTamperSensor(coordinator, entry, zone_idx, zone_name)
        )

    async_add_entities(entities)


class OrisecZoneSensor(CoordinatorEntity[OrisecCoordinator], BinarySensorEntity):

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: OrisecCoordinator,
        entry: ConfigEntry,
        zone_idx: int,
        zone_type: int,
        zone_name: str,
    ) -> None:
        super().__init__(coordinator)
        self._zone_idx = zone_idx
        self._attr_name = zone_name
        self._attr_unique_id = f"{entry.entry_id}_zone_{zone_idx + 1}"

        dc_str = ZONE_TYPE_TO_DEVICE_CLASS.get(zone_type)
        if dc_str and dc_str in _DEVICE_CLASS_MAP:
            self._attr_device_class = _DEVICE_CLASS_MAP[dc_str]

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
        return bool(self.coordinator.get_zone_status_value(self._zone_idx) & 0x01)

    @property
    def extra_state_attributes(self):
        zone_type = self.coordinator.get_zone_type(self._zone_idx)
        raw = self.coordinator.get_zone_status_value(self._zone_idx)
        attrs = {
            "zone_number": self._zone_idx + 1,
            "zone_type": ZONE_TYPE_NAMES.get(zone_type, f"Type {zone_type}"),
            "raw_status": f"0x{raw:04x}",
        }
        timer = self.coordinator.get_zone_timer(self._zone_idx)
        if timer > 0:
            attrs["activity_timer"] = timer
        return attrs


class OrisecZoneTamperSensor(CoordinatorEntity[OrisecCoordinator], BinarySensorEntity):

    _attr_has_entity_name = True
    _attr_device_class = BinarySensorDeviceClass.TAMPER
    _attr_entity_registry_enabled_default = False

    def __init__(
        self,
        coordinator: OrisecCoordinator,
        entry: ConfigEntry,
        zone_idx: int,
        zone_name: str,
    ) -> None:
        super().__init__(coordinator)
        self._zone_idx = zone_idx
        self._attr_name = f"{zone_name} Tamper"
        self._attr_unique_id = f"{entry.entry_id}_zone_{zone_idx + 1}_tamper"

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
        return bool(self.coordinator.get_zone_status_value(self._zone_idx) & 0x02)
