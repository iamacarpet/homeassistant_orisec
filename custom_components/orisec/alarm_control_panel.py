"""Alarm control panel entities for Orisec ControlPlus2."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.alarm_control_panel import (
    AlarmControlPanelEntity,
    AlarmControlPanelEntityFeature,
    AlarmControlPanelState,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import OrisecCoordinator

_LOGGER = logging.getLogger(__name__)

_STATE_MAP = {
    "triggered": AlarmControlPanelState.TRIGGERED,
    "armed_away": AlarmControlPanelState.ARMED_AWAY,
    "armed_home": AlarmControlPanelState.ARMED_HOME,
    "arming": AlarmControlPanelState.ARMING,
    "pending": AlarmControlPanelState.PENDING,
    "disarmed": AlarmControlPanelState.DISARMED,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: OrisecCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[AlarmControlPanelEntity] = []

    for area_idx in range(coordinator.max_areas):
        area_bit = 1 << area_idx
        if not (coordinator.user_area & area_bit):
            continue

        entities.append(
            OrisecAlarmPanel(coordinator, entry, area_idx)
        )

        for part in range(3):
            if coordinator.part_arm_mask & (1 << part):
                entities.append(
                    OrisecPartArmPanel(coordinator, entry, area_idx, part + 1)
                )

    async_add_entities(entities)


class OrisecAlarmPanel(CoordinatorEntity[OrisecCoordinator], AlarmControlPanelEntity):

    _attr_has_entity_name = True
    _attr_supported_features = (
        AlarmControlPanelEntityFeature.ARM_AWAY
        | AlarmControlPanelEntityFeature.ARM_HOME
        | AlarmControlPanelEntityFeature.TRIGGER
    )
    _attr_code_arm_required = False

    def __init__(
        self,
        coordinator: OrisecCoordinator,
        entry: ConfigEntry,
        area_idx: int,
    ) -> None:
        super().__init__(coordinator)
        self._area_idx = area_idx
        area_name = (
            coordinator.area_names[area_idx]
            if area_idx < len(coordinator.area_names)
            and coordinator.area_names[area_idx]
            else f"Area {area_idx + 1}"
        )
        self._attr_name = area_name
        self._attr_unique_id = f"{entry.entry_id}_alarm_area_{area_idx + 1}"

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self.coordinator.serial or self.coordinator.host)},
            "name": f"Orisec {self.coordinator.panel_type or 'Panel'}",
            "manufacturer": "Orisec",
            "model": self.coordinator.panel_type,
            "sw_version": self.coordinator.panel_version,
        }

    @callback
    def _handle_coordinator_update(self) -> None:
        state_str = self.coordinator.get_alarm_state_for_area(self._area_idx)
        self._attr_alarm_state = _STATE_MAP.get(
            state_str, AlarmControlPanelState.DISARMED
        )
        self.async_write_ha_state()

    @property
    def alarm_state(self) -> AlarmControlPanelState:
        state_str = self.coordinator.get_alarm_state_for_area(self._area_idx)
        return _STATE_MAP.get(state_str, AlarmControlPanelState.DISARMED)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        area_bit = 1 << self._area_idx
        sos = self.coordinator.sys_output_state
        from .const import (
            SOS_READY,
            SOS_TROUBLE,
            SOS_BYPASS,
            SOS_BELL,
            SOS_AC_FAULT,
            SOS_BATTERY_FAULT,
        )
        return {
            "ready": bool(sos[SOS_READY] & area_bit),
            "trouble": bool(sos[SOS_TROUBLE] & area_bit),
            "bypass": bool(sos[SOS_BYPASS] & area_bit),
            "bell": bool(sos[SOS_BELL] & area_bit),
            "ac_fault": bool(sos[SOS_AC_FAULT] & area_bit),
            "battery_fault": bool(sos[SOS_BATTERY_FAULT] & area_bit),
            "active_part_arm": self.coordinator.get_active_part_arm(self._area_idx),
        }

    async def async_alarm_arm_away(self, code: str | None = None) -> None:
        area_mask = 1 << self._area_idx
        await self.coordinator.async_arm_away(area_mask)

    async def async_alarm_arm_home(self, code: str | None = None) -> None:
        area_mask = 1 << self._area_idx
        await self.coordinator.async_arm_home(area_mask, part=1)

    async def async_alarm_disarm(self, code: str | None = None) -> None:
        area_mask = 1 << self._area_idx
        await self.coordinator.async_disarm(area_mask)

    async def async_alarm_trigger(self, code: str | None = None) -> None:
        pass


class OrisecPartArmPanel(CoordinatorEntity[OrisecCoordinator], AlarmControlPanelEntity):

    _attr_has_entity_name = True
    _attr_supported_features = AlarmControlPanelEntityFeature.ARM_HOME
    _attr_code_arm_required = False

    def __init__(
        self,
        coordinator: OrisecCoordinator,
        entry: ConfigEntry,
        area_idx: int,
        part: int,
    ) -> None:
        super().__init__(coordinator)
        self._area_idx = area_idx
        self._part = part

        area_name = (
            coordinator.area_names[area_idx]
            if area_idx < len(coordinator.area_names)
            and coordinator.area_names[area_idx]
            else f"Area {area_idx + 1}"
        )
        part_name = (
            coordinator.part_arm_names[part - 1]
            if part - 1 < len(coordinator.part_arm_names)
            and coordinator.part_arm_names[part - 1]
            else f"Part Arm {part}"
        )
        self._attr_name = f"{area_name} - {part_name}"
        self._attr_unique_id = (
            f"{entry.entry_id}_alarm_area_{area_idx + 1}_part_{part}"
        )

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
    def alarm_state(self) -> AlarmControlPanelState:
        active_part = self.coordinator.get_active_part_arm(self._area_idx)
        if active_part == self._part:
            return AlarmControlPanelState.ARMED_HOME
        base = self.coordinator.get_alarm_state_for_area(self._area_idx)
        if base == "triggered":
            return AlarmControlPanelState.TRIGGERED
        if base == "arming":
            return AlarmControlPanelState.ARMING
        if base == "pending":
            return AlarmControlPanelState.PENDING
        return AlarmControlPanelState.DISARMED

    @callback
    def _handle_coordinator_update(self) -> None:
        active_part = self.coordinator.get_active_part_arm(self._area_idx)
        if active_part == self._part:
            self._attr_alarm_state = AlarmControlPanelState.ARMED_HOME
        else:
            base = self.coordinator.get_alarm_state_for_area(self._area_idx)
            self._attr_alarm_state = _STATE_MAP.get(base, AlarmControlPanelState.DISARMED)
        self.async_write_ha_state()

    async def async_alarm_arm_home(self, code: str | None = None) -> None:
        area_mask = 1 << self._area_idx
        await self.coordinator.async_arm_home(area_mask, part=self._part)

    async def async_alarm_disarm(self, code: str | None = None) -> None:
        area_mask = 1 << self._area_idx
        await self.coordinator.async_disarm(area_mask)
