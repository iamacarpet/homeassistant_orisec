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
    "armed_night": AlarmControlPanelState.ARMED_NIGHT,
    "armed_vacation": AlarmControlPanelState.ARMED_VACATION,
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
        if not (coordinator.user_area & (1 << area_idx)):
            continue
        entities.append(OrisecAlarmPanel(coordinator, entry, area_idx))

    async_add_entities(entities)


class OrisecAlarmPanel(CoordinatorEntity[OrisecCoordinator], AlarmControlPanelEntity):

    _attr_has_entity_name = True
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
            if area_idx < len(coordinator.area_names) and coordinator.area_names[area_idx]
            else f"Area {area_idx + 1}"
        )
        self._attr_name = area_name
        self._attr_unique_id = f"{entry.entry_id}_alarm_area_{area_idx + 1}"

        # Full Set is always available; part arms depend on panel configuration.
        # HA labels: Away = Full Set, Home = Part 1, Night = Part 2, Vacation = Part 3.
        features = AlarmControlPanelEntityFeature.ARM_AWAY
        if coordinator.part_arm_mask & 1:
            features |= AlarmControlPanelEntityFeature.ARM_HOME
        if coordinator.part_arm_mask & 2:
            features |= AlarmControlPanelEntityFeature.ARM_NIGHT
        if coordinator.part_arm_mask & 4:
            features |= AlarmControlPanelEntityFeature.ARM_VACATION
        self._attr_supported_features = features

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
        state_str = self.coordinator.get_alarm_state_for_area(self._area_idx)
        return _STATE_MAP.get(state_str, AlarmControlPanelState.DISARMED)

    @callback
    def _handle_coordinator_update(self) -> None:
        state_str = self.coordinator.get_alarm_state_for_area(self._area_idx)
        self._attr_alarm_state = _STATE_MAP.get(state_str, AlarmControlPanelState.DISARMED)
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        area_bit = 1 << self._area_idx
        sos = self.coordinator.sys_output_state
        from .const import (
            SOS_READY, SOS_TROUBLE, SOS_BYPASS, SOS_BELL, SOS_AC_FAULT, SOS_BATTERY_FAULT,
        )
        attrs: dict[str, Any] = {
            "ready": bool(sos[SOS_READY] & area_bit),
            "trouble": bool(sos[SOS_TROUBLE] & area_bit),
            "bypass": bool(sos[SOS_BYPASS] & area_bit),
            "bell": bool(sos[SOS_BELL] & area_bit),
            "ac_fault": bool(sos[SOS_AC_FAULT] & area_bit),
            "battery_fault": bool(sos[SOS_BATTERY_FAULT] & area_bit),
        }
        # Surface the panel's own names for each arm mode so users know what
        # "Away / Home / Night / Vacation" actually means on their system.
        names = self.coordinator.part_arm_names
        mask = self.coordinator.part_arm_mask
        if mask & 1 and len(names) > 0 and names[0]:
            attrs["home_mode"] = names[0]
        if mask & 2 and len(names) > 1 and names[1]:
            attrs["night_mode"] = names[1]
        if mask & 4 and len(names) > 2 and names[2]:
            attrs["vacation_mode"] = names[2]
        return attrs

    async def async_alarm_arm_away(self, code: str | None = None) -> None:
        await self.coordinator.async_arm_away(1 << self._area_idx)

    async def async_alarm_arm_home(self, code: str | None = None) -> None:
        await self.coordinator.async_arm_home(1 << self._area_idx, part=1)

    async def async_alarm_arm_night(self, code: str | None = None) -> None:
        await self.coordinator.async_arm_home(1 << self._area_idx, part=2)

    async def async_alarm_arm_vacation(self, code: str | None = None) -> None:
        await self.coordinator.async_arm_home(1 << self._area_idx, part=3)

    async def async_alarm_disarm(self, code: str | None = None) -> None:
        await self.coordinator.async_disarm(1 << self._area_idx)

    async def async_alarm_trigger(self, code: str | None = None) -> None:
        pass
