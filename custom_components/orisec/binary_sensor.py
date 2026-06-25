"""Binary sensor entities for Orisec ControlPlus2 zones and system status."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    ZONE_TYPE_NOT_USED,
    ZONE_TYPE_NAMES,
    ZONE_TYPE_TO_DEVICE_CLASS,
    SOS_PANEL_AC_ON,
    SOS_BATTERY_FAULT,
    SOS_TAMPER,
    SOS_BELL,
    SOS_TROUBLE,
)
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

# (key, sos_idx, device_class, name, entity_category)
_SYSTEM_SENSORS: list[
    tuple[str, int, BinarySensorDeviceClass | None, str, EntityCategory | None]
] = [
    ("ac_power", SOS_PANEL_AC_ON, BinarySensorDeviceClass.PLUG, "AC Power", None),
    ("battery_fault", SOS_BATTERY_FAULT, BinarySensorDeviceClass.BATTERY, "Battery Fault", None),
    ("tamper", SOS_TAMPER, BinarySensorDeviceClass.TAMPER, "Tamper", None),
    ("bell", SOS_BELL, BinarySensorDeviceClass.SOUND, "Bell Active", None),
    ("trouble", SOS_TROUBLE, BinarySensorDeviceClass.PROBLEM, "Trouble", EntityCategory.DIAGNOSTIC),
]


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

    for key, sos_idx, device_class, name, entity_category in _SYSTEM_SENSORS:
        entities.append(
            OrisecSystemBinarySensor(
                coordinator, entry, key, sos_idx, device_class, name, entity_category
            )
        )

    async_add_entities(entities)


def _device_info(coordinator: OrisecCoordinator) -> dict:
    return {
        "identifiers": {(DOMAIN, coordinator.serial or coordinator.host)},
        "name": f"Orisec {coordinator.panel_type or 'Panel'}",
        "manufacturer": "Orisec",
        "model": coordinator.panel_type,
        "sw_version": coordinator.panel_version,
    }


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
        return _device_info(self.coordinator)

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.get_zone_status_value(self._zone_idx) & 0x01)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        zone_type = self.coordinator.get_zone_type(self._zone_idx)
        raw = self.coordinator.get_zone_status_value(self._zone_idx)
        attrs: dict[str, Any] = {
            "zone_number": self._zone_idx + 1,
            "zone_type": ZONE_TYPE_NAMES.get(zone_type, f"Type {zone_type}"),
            "raw_status": f"0x{raw:04x}",
            "bypassed": self.coordinator.get_zone_bypass(self._zone_idx),
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
        return _device_info(self.coordinator)

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.get_zone_status_value(self._zone_idx) & 0x02)


class OrisecSystemBinarySensor(CoordinatorEntity[OrisecCoordinator], BinarySensorEntity):

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: OrisecCoordinator,
        entry: ConfigEntry,
        key: str,
        sos_idx: int,
        device_class: BinarySensorDeviceClass | None,
        name: str,
        entity_category: EntityCategory | None,
    ) -> None:
        super().__init__(coordinator)
        self._sos_idx = sos_idx
        self._attr_device_class = device_class
        self._attr_name = name
        self._attr_unique_id = f"{entry.entry_id}_sys_{key}"
        if entity_category is not None:
            self._attr_entity_category = entity_category

    @property
    def device_info(self):
        return _device_info(self.coordinator)

    @property
    def is_on(self) -> bool:
        sos = self.coordinator.sys_output_state
        if not sos or self._sos_idx >= len(sos):
            return False
        return bool(sos[self._sos_idx] & 0xFF)
