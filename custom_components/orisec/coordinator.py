"""Data update coordinator for Orisec ControlPlus2."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    DOMAIN,
    POLL_INTERVAL,
    CMD_LCD,
    QUERY_AREA_ARM_ATT,
    QUERY_AREA_TEXTS,
    QUERY_MAX_AREAS,
    QUERY_MAX_REM_OUTPUTS,
    QUERY_MAX_ZONES,
    QUERY_PANEL_TIME_H,
    QUERY_PANEL_TIME_M,
    QUERY_PANEL_TIME_S,
    QUERY_PART_ARM_TEXTS,
    QUERY_REM_OUTPUT_STATE,
    QUERY_REM_OUTPUT_TEXTS,
    QUERY_SYS_OUTPUT_STATE,
    QUERY_SYS_TEXT,
    QUERY_ZONE_AREAS,
    QUERY_ZONE_BYPASS,
    QUERY_ZONE_STATUS,
    QUERY_ZONE_TEXTS,
    QUERY_ZONE_TIMERS,
    QUERY_ZONE_TYPES,
    QUERY_USER_TYPE,
    QUERY_UDL_OPTION,
    CMD_PANEL_STATE,
    SOS_ALARM,
    SOS_ARMED,
    SOS_BELL,
    SOS_FIRE,
    SOS_IN_ALARM,
    SOS_IN_ENTRY,
    SOS_IN_EXIT,
    SOS_PA,
    SOS_PART_ARMED,
    SOS_PART1,
    SOS_PART2,
    SOS_PART3,
    KEY_FULL_ARM,
    KEY_PART1,
    KEY_PART2,
    KEY_PART3,
    KEY_DISARM,
    KEY_RESET,
    ZONE_TYPE_NOT_USED,
)
from .protocol import (
    OrisecConnection,
    ParsedResponse,
    add_udl_pkt,
    load_udl_pkt,
    parse_responses,
)

_LOGGER = logging.getLogger(__name__)

SETUP_RETRY_DELAY = 5


class OrisecCoordinator(DataUpdateCoordinator[dict[str, Any]]):

    def __init__(
        self,
        hass: HomeAssistant,
        host: str,
        port: int,
        password: str,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=POLL_INTERVAL),
        )
        self._host = host
        self._port = port
        self._password = password
        self._conn = OrisecConnection(host, port)
        self._stage = 0
        self._poll_index = 0

        self.panel_type: str | None = None
        self.panel_version: str | None = None
        self.serial: str | None = None
        self.max_zones: int = 0
        self.max_areas: int = 0
        self.max_rem_outputs: int = 0
        self.part_arm_mask: int = 0
        self.user_area: int = 0
        self.user_number: int = 0

        self.zone_names: list[str] = []
        self.zone_types: bytes = b""
        self.zone_areas: bytes = b""
        self.area_names: list[str] = []
        self.rem_output_names: list[str] = []
        self.part_arm_names: list[str] = []

        self.sys_output_state: list[int] = [0] * 100
        self.zone_status: bytes = b""
        self.zone_timers: bytes = b""
        self.rem_output_state: bytes = b""
        self.zone_bypass: bytes = b""

        self._prev_alarm_state: dict[int, bool] = {}
        self._prev_arm_state: dict[int, str] = {}

        self._keypad_subscribers: int = 0
        self._lcd_lines: list[str] = ["", "", "", ""]
        self._panel_time: list[int] = [0, 0, 0]
        self._lcd_callbacks: list[Callable] = []

    @property
    def host(self) -> str:
        return self._host

    @property
    def connected(self) -> bool:
        return self._conn.connected and self._stage >= 3

    async def async_setup(self) -> None:
        await self._conn.connect()
        await self._do_login()
        await self._do_config()
        await self._do_initial_data()
        self._stage = 3

    async def _do_login(self) -> None:
        result = await self._conn.login(self._password)
        if not result.logged_in:
            err = result.error
            if err == 3:
                raise UpdateFailed("Password rejected by panel")
            raise UpdateFailed(f"Login failed (error={err})")

        self.panel_type = result.panel_type
        self.panel_version = result.panel_version
        self.serial = result.serial
        self.max_zones = result.max_zones
        self.max_areas = result.max_areas
        self.max_rem_outputs = result.max_rem_outputs
        self.part_arm_mask = result.part_arm_mask
        self.user_area = result.user_area
        self.user_number = result.user_number

    async def _do_config(self) -> None:
        if self.max_zones == 0:
            result = await self._conn.multi_query([
                (QUERY_MAX_ZONES, 1, 1),
                (QUERY_MAX_AREAS, 1, 1),
                (QUERY_MAX_REM_OUTPUTS, 1, 1),
                (QUERY_USER_TYPE, self.user_number + 1, 1),
                (QUERY_UDL_OPTION, 1, 1),
            ])
            if result.max_zones > 0:
                self.max_zones = result.max_zones
            if result.max_areas > 0:
                self.max_areas = result.max_areas
            if result.max_rem_outputs > 0:
                self.max_rem_outputs = result.max_rem_outputs

        if self.max_zones == 0:
            self.max_zones = 20
        if self.max_areas == 0:
            self.max_areas = 2

    async def _do_initial_data(self) -> None:
        await asyncio.sleep(0.3)
        queries: list[tuple[int, int, int]] = [
            (QUERY_ZONE_TYPES, 1, self.max_zones),
            (QUERY_ZONE_AREAS, 1, min(self.max_zones, 100)),
            (QUERY_AREA_TEXTS, 1, self.max_areas),
        ]
        result = await self._conn.multi_query(queries)
        self.zone_types = result.zone_types
        self.zone_areas = result.zone_areas
        self.area_names = result.area_names

        await asyncio.sleep(0.3)

        remaining = self.max_zones
        start = 1
        while remaining > 0:
            batch = min(remaining, 15)
            r = await self._conn.query(QUERY_ZONE_TEXTS, start, batch)
            if start == 1:
                self.zone_names = r.zone_names
            else:
                self.zone_names.extend(r.zone_names)
            start += batch
            remaining -= batch
            if remaining > 0:
                await asyncio.sleep(0.2)

        if self.max_rem_outputs > 0:
            await asyncio.sleep(0.3)
            r = await self._conn.multi_query([
                (QUERY_REM_OUTPUT_TEXTS, 1, self.max_rem_outputs),
                (QUERY_REM_OUTPUT_STATE, 1, self.max_rem_outputs + 1),
            ])
            self.rem_output_names = r.rem_output_names
            self.rem_output_state = r.rem_output_state

        await asyncio.sleep(0.3)
        r = await self._conn.multi_query([
            (QUERY_PART_ARM_TEXTS, 1, 3),
            (QUERY_AREA_ARM_ATT, 1, self.max_areas),
            (QUERY_SYS_OUTPUT_STATE, 1, 65),
            (CMD_PANEL_STATE, 1, 1),
            (QUERY_ZONE_STATUS, 1, self.max_zones),
        ])
        self.part_arm_names = r.part_arm_names
        self.sys_output_state = r.sys_output_state
        self.zone_status = r.zone_status

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            if not self.connected:
                await self._conn.disconnect()
                await self._conn.connect()
                await self._do_login()
                await self._do_config()
                await self._do_initial_data()
                self._stage = 3

            queries: list[tuple[int, int, int]] = [
                (QUERY_SYS_OUTPUT_STATE, 1, 65),
                (CMD_PANEL_STATE, 1, 1),
                (QUERY_ZONE_STATUS, 1, self.max_zones),
            ]

            if self._poll_index % 2 == 0:
                queries.append((QUERY_ZONE_TIMERS, 1, self.max_zones))
            else:
                queries.append((QUERY_ZONE_BYPASS, 1, self.max_zones))

            if self.max_rem_outputs > 0 and self._poll_index % 3 == 0:
                queries.append(
                    (QUERY_REM_OUTPUT_STATE, 1, self.max_rem_outputs + 1)
                )

            if self._keypad_subscribers > 0:
                queries.extend([
                    (QUERY_PANEL_TIME_H, 1, 1),
                    (QUERY_PANEL_TIME_M, 1, 1),
                    (QUERY_PANEL_TIME_S, 1, 1),
                    (CMD_LCD, 1, 1),
                ])

            self._poll_index += 1

            result = await self._conn.multi_query(queries)

            self.sys_output_state = result.sys_output_state
            if result.zone_status:
                self.zone_status = result.zone_status
            if result.zone_timers:
                self.zone_timers = result.zone_timers
            if result.zone_bypass:
                self.zone_bypass = result.zone_bypass
            if result.rem_output_state:
                self.rem_output_state = result.rem_output_state

            if self._keypad_subscribers > 0 and result.lcd_raw:
                self._panel_time = result.panel_time[:]
                new_lines = self._parse_lcd_text(
                    result.lcd_raw, self._panel_time
                )
                if new_lines != self._lcd_lines:
                    self._lcd_lines = new_lines
                    self._notify_lcd_subscribers()

            self._check_alarm_events()

            return {
                "sys_output_state": self.sys_output_state,
                "zone_status": self.zone_status,
                "zone_timers": self.zone_timers,
                "zone_bypass": self.zone_bypass,
                "rem_output_state": self.rem_output_state,
            }

        except Exception as err:
            self._stage = 0
            try:
                await self._conn.disconnect()
            except Exception:
                pass
            if isinstance(err, UpdateFailed):
                raise
            raise UpdateFailed(f"Communication error: {err}") from err

    @callback
    def _check_alarm_events(self) -> None:
        sos = self.sys_output_state
        for area_idx in range(self.max_areas):
            bit = 1 << area_idx
            area_name = (
                self.area_names[area_idx]
                if area_idx < len(self.area_names) and self.area_names[area_idx]
                else f"Area {area_idx + 1}"
            )

            in_alarm = bool(sos[SOS_ALARM] & bit) or bool(sos[SOS_IN_ALARM] & bit)
            prev_alarm = self._prev_alarm_state.get(area_idx, False)
            if in_alarm and not prev_alarm:
                self.hass.bus.async_fire(
                    f"{DOMAIN}_alarm_triggered",
                    {
                        "area": area_idx + 1,
                        "area_name": area_name,
                        "fire": bool(sos[SOS_FIRE] & bit),
                        "pa": bool(sos[SOS_PA] & bit),
                        "bell": bool(sos[SOS_BELL] & bit),
                    },
                )
            elif prev_alarm and not in_alarm:
                self.hass.bus.async_fire(
                    f"{DOMAIN}_alarm_cleared",
                    {
                        "area": area_idx + 1,
                        "area_name": area_name,
                    },
                )
            self._prev_alarm_state[area_idx] = in_alarm

            current_state = self.get_alarm_state_for_area(area_idx)
            prev_state = self._prev_arm_state.get(area_idx)
            if prev_state is not None and current_state != prev_state:
                self.hass.bus.async_fire(
                    f"{DOMAIN}_state_changed",
                    {
                        "area": area_idx + 1,
                        "area_name": area_name,
                        "old_state": prev_state,
                        "new_state": current_state,
                    },
                )
            self._prev_arm_state[area_idx] = current_state

    async def async_send_keypress(self, key_code: int, area_mask: int) -> None:
        if not self._conn.connected:
            raise ConnectionError("Not connected to panel")
        await self._conn.send_keypress(key_code, area_mask)
        await asyncio.sleep(0.5)
        await self.async_request_refresh()

    async def async_arm_away(self, area_mask: int) -> None:
        await self.async_send_keypress(KEY_FULL_ARM, area_mask)

    async def async_arm_home(self, area_mask: int, part: int = 1) -> None:
        key = {1: KEY_PART1, 2: KEY_PART2, 3: KEY_PART3}.get(part, KEY_PART1)
        await self.async_send_keypress(key, area_mask)

    async def async_disarm(self, area_mask: int) -> None:
        await self.async_send_keypress(KEY_DISARM, area_mask)

    async def async_toggle_output(self, output_index: int) -> None:
        if not self._conn.connected:
            raise ConnectionError("Not connected to panel")
        current = 0
        if output_index < len(self.rem_output_state):
            current = self.rem_output_state[output_index]
        await self._conn.toggle_output(output_index, current)
        await asyncio.sleep(0.3)
        r = await self._conn.query(
            QUERY_REM_OUTPUT_STATE, 1, self.max_rem_outputs + 1
        )
        if r.rem_output_state:
            self.rem_output_state = r.rem_output_state
        await self.async_request_refresh()

    async def async_shutdown(self) -> None:
        await self._conn.disconnect()
        self._stage = 0

    def get_zone_bypass(self, zone_index: int) -> bool:
        if not self.zone_bypass or zone_index >= len(self.zone_bypass):
            return False
        return bool(self.zone_bypass[zone_index])

    def get_zone_type(self, zone_index: int) -> int:
        if zone_index < len(self.zone_types):
            return self.zone_types[zone_index]
        return ZONE_TYPE_NOT_USED

    def get_zone_name(self, zone_index: int) -> str:
        if zone_index < len(self.zone_names):
            return self.zone_names[zone_index]
        return ""

    def get_zone_status_value(self, zone_index: int) -> int:
        if not self.zone_status:
            return 0
        byte_idx = zone_index * 2
        if byte_idx + 1 < len(self.zone_status):
            return self.zone_status[byte_idx] | (self.zone_status[byte_idx + 1] << 8)
        if byte_idx < len(self.zone_status):
            return self.zone_status[byte_idx]
        return 0

    def get_zone_timer(self, zone_index: int) -> int:
        if not self.zone_timers:
            return 0
        byte_idx = zone_index * 2
        if byte_idx + 1 < len(self.zone_timers):
            return self.zone_timers[byte_idx] | (self.zone_timers[byte_idx + 1] << 8)
        if byte_idx < len(self.zone_timers):
            return self.zone_timers[byte_idx]
        return 0

    def get_output_state(self, output_index: int) -> bool:
        if output_index < len(self.rem_output_state):
            return bool(self.rem_output_state[output_index])
        return False

    def get_alarm_state_for_area(self, area_idx: int) -> str:
        sos = self.sys_output_state
        bit = 1 << area_idx

        if sos[SOS_ALARM] & bit or sos[SOS_IN_ALARM] & bit:
            return "triggered"
        if sos[SOS_ARMED] & bit:
            if sos[SOS_PART_ARMED] & bit:
                if sos[SOS_PART2] & bit:
                    return "armed_night"
                if sos[SOS_PART3] & bit:
                    return "armed_vacation"
                return "armed_home"
            return "armed_away"
        if sos[SOS_IN_EXIT] & bit:
            return "arming"
        if sos[SOS_IN_ENTRY] & bit:
            return "pending"
        return "disarmed"

    def get_active_part_arm(self, area_idx: int) -> int | None:
        sos = self.sys_output_state
        bit = 1 << area_idx
        if not (sos[SOS_PART_ARMED] & bit):
            return None
        if sos[SOS_PART1] & bit:
            return 1
        if sos[SOS_PART2] & bit:
            return 2
        if sos[SOS_PART3] & bit:
            return 3
        return 1

    def is_area_ready(self, area_idx: int) -> bool:
        from .const import SOS_READY
        return bool(self.sys_output_state[SOS_READY] & (1 << area_idx))

    # ── Keypad / LCD ────────────────────────────────────────────────────────

    _VALID_KEYPAD_CHARS = frozenset("0123456789FPAYNOCRludr ")

    def keypad_subscribe(self, send_callback: Callable) -> Callable:
        self._keypad_subscribers += 1
        self._lcd_callbacks.append(send_callback)
        send_callback(self._get_lcd_state())

        def unsubscribe() -> None:
            self._keypad_subscribers = max(0, self._keypad_subscribers - 1)
            if send_callback in self._lcd_callbacks:
                self._lcd_callbacks.remove(send_callback)

        return unsubscribe

    def _get_lcd_state(self) -> dict:
        return {
            "lines": self._lcd_lines[:],
            "time": (
                f"{self._panel_time[0]:02d}:"
                f"{self._panel_time[1]:02d}:"
                f"{self._panel_time[2]:02d}"
            ),
        }

    @callback
    def _notify_lcd_subscribers(self) -> None:
        state = self._get_lcd_state()
        for cb in self._lcd_callbacks[:]:
            try:
                cb(state)
            except Exception:
                _LOGGER.debug("Error notifying LCD subscriber", exc_info=True)

    async def async_send_keypad_char(self, char: str) -> None:
        if not self._conn.connected:
            raise ConnectionError("Not connected to panel")
        if len(char) != 1 or char not in self._VALID_KEYPAD_CHARS:
            raise ValueError(f"Invalid keypad character: {char!r}")
        await self._conn.send_keypad_char(char)
        if self._keypad_subscribers > 0:
            await self.async_request_refresh()

    @staticmethod
    def _parse_lcd_text(raw: bytes, panel_time: list[int]) -> list[str]:
        lines: list[str] = ["", "", "", ""]
        cur = -1
        i = 0
        while i < len(raw):
            b = raw[i]
            if b == 17:
                cur = 0 if cur == -1 else min(cur + 1, 3)
                lines[cur] = ""
            elif 18 <= b <= 21:
                cur = b - 18
                lines[cur] = ""
            elif b == 12:
                if cur >= 0:
                    lines[cur] += (
                        f"{panel_time[0]:02d}:{panel_time[1]:02d}"
                        f".{panel_time[2]:02d}"
                    )
            elif b == 14:
                i = min(i + 4, len(raw) - 1)
            elif b in (7, 8, 16, 26):
                i = min(i + 1, len(raw) - 1)
            elif 32 <= b <= 126 and cur >= 0:
                lines[cur] += chr(b)
            elif 126 < b <= 173 and cur >= 0:
                _ICON_MAP = {
                    127: "<", 128: "E", 155: ":", 156: ".",
                    159: "[x]", 160: "[ ]", 163: "^", 164: "v",
                    165: ">", 166: "<", 170: "*", 172: "v", 173: "^",
                }
                lines[cur] += _ICON_MAP.get(b, "")
            i += 1
        return [line.rstrip() for line in lines]
