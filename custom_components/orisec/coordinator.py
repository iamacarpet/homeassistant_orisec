"""Data update coordinator for Orisec ControlPlus2."""

from __future__ import annotations

import asyncio
import logging
import random
import time
from collections import deque
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    COMMAND_TIMEOUT,
    CONFIG_FLOW_GRACE_PERIOD,
    DIAGNOSTIC_HISTORY_SIZE,
    DOMAIN,
    KEYPAD_POLL_INTERVAL,
    POLL_FAILURE_GRACE,
    POLL_INTERVAL,
    RECONNECT_BACKOFF_BASE,
    RECONNECT_BACKOFF_MAX,
    REFUSED_BACKOFF_BASE,
    REFUSED_BACKOFF_MAX,
    SETUP_BACKOFF_BASE,
    SETUP_BACKOFF_MAX,
    SETUP_MAX_RETRIES,
    UDP_TIMEOUT,
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
    SOS_BATTERY_FAULT,
    SOS_BELL,
    SOS_BYPASS,
    SOS_FIRE,
    SOS_IN_ALARM,
    SOS_IN_ENTRY,
    SOS_IN_EXIT,
    SOS_PA,
    SOS_PANEL_AC_ON,
    SOS_PART_ARMED,
    SOS_PART1,
    SOS_PART2,
    SOS_PART3,
    SOS_READY,
    SOS_TROUBLE,
    KEY_FULL_ARM,
    KEY_PART1,
    KEY_PART2,
    KEY_PART3,
    KEY_DISARM,
    KEY_RESET,
    ZONE_TYPE_NOT_USED,
)
from .protocol import (
    LocalPortInUseError,
    OrisecConnection,
    PanelNoResponseError,
    PanelRefusedError,
    PanelUDPError,
    ParsedResponse,
    add_udl_pkt,
    load_udl_pkt,
    parse_responses,
)
from .throttled_log import ThrottledLog

_LOGGER = logging.getLogger(__name__)
_THROTTLED = ThrottledLog(_LOGGER)

SETUP_RETRY_DELAY = 5

# Panel configuration that shapes the entities; cached so HA can start without the panel.
_METADATA_FIELDS = (
    "panel_type", "panel_version", "serial", "max_zones", "max_areas",
    "max_rem_outputs", "part_arm_mask", "user_area", "user_number",
    "zone_names", "area_names", "rem_output_names", "part_arm_names",
)
_METADATA_BYTES_FIELDS = ("zone_types", "zone_areas")

_PANEL_ERRORS = {3: "password rejected", 4: "not logged in", 5: "command not supported"}


def _describe_panel_error(code: int | None) -> str:
    return f"error {code}: {_PANEL_ERRORS[code]}" if code in _PANEL_ERRORS else f"error {code}"


class PanelSessionError(UpdateFailed):
    """The panel answered with an error instead of status, e.g. because the login expired."""


class PanelLoginError(UpdateFailed):
    """The panel rejected the login."""


class PanelInvalidReplyError(UpdateFailed):
    """The panel replied, but without the status data that was asked for."""


def failure_category(err: BaseException) -> str:
    """Name what kind of failure an error is, to tell apart the causes of an outage.

    no_response: requests went out but nothing usable came back (lost or dropped replies).
    refused: the panel's IP module answered ICMP port-unreachable.
    udp_error: the host couldn't send or got a network error (e.g. no route).
    port_in_use: the fixed local port is held by another socket, so nothing was sent.
    session_error / login_rejected / invalid_reply: the panel answered, but not with data.
    """
    if isinstance(err, LocalPortInUseError):
        return "port_in_use"
    if isinstance(err, PanelRefusedError):
        return "refused"
    if isinstance(err, PanelUDPError):
        return "udp_error"
    if isinstance(err, (PanelNoResponseError, asyncio.TimeoutError)):
        return "no_response"
    if isinstance(err, PanelSessionError):
        return "session_error"
    if isinstance(err, PanelLoginError):
        return "login_rejected"
    if isinstance(err, PanelInvalidReplyError):
        return "invalid_reply"
    if isinstance(err, OSError):
        # Includes ConnectionError, e.g. "Not connected" when the socket is gone.
        return "socket_error"
    return "error"


def describe_failure(err: BaseException) -> str:
    return f"{failure_category(err)}: {err or type(err).__name__}"


def _timestamp(when: float | None) -> str | None:
    """Local time with UTC offset, matching the clock Home Assistant's log uses."""
    if when is None:
        return None
    return datetime.fromtimestamp(when).astimezone().isoformat(timespec="milliseconds")


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

        self._event_log: list[dict] = []

        self._keypad_subscribers: int = 0
        self._lcd_raw: bytes = b""
        self._panel_time: list[int] = [0, 0, 0]
        self._lcd_callbacks: list[Callable] = []

        self._panel_callbacks: list[Callable] = []

        self._reconnect_task: asyncio.Task | None = None
        self._reconnect_attempts: int = 0
        self._last_error_refused: bool = False
        self._last_poll_ok: float = time.monotonic()
        self._consecutive_failures: int = 0
        self._connection_drops: int = 0
        self._last_error: str | None = None

        # Diagnostics. Times are wall-clock (time.time()).
        self._polls: int = 0
        self._last_poll_at: float | None = None
        # When the panel's status block was last read and applied: entity state is
        # confirmed by the panel only as of this time.
        self._last_status_at: float | None = None
        self._session_errors: int = 0
        self._last_unavailable_at: float | None = None
        self._last_unavailable_reason: str | None = None
        self._last_reconnect_at: float | None = None
        self._last_reconnect_reason: str | None = None
        self._history: deque[dict[str, Any]] = deque(maxlen=DIAGNOSTIC_HISTORY_SIZE)

        # False until names/types are read from the panel in this run (a cache restore doesn't count).
        self._metadata_fresh: bool = False
        self.on_metadata_updated: Callable[[], None] | None = None

    @property
    def host(self) -> str:
        return self._host

    @property
    def connected(self) -> bool:
        return self._conn.connected and self._stage >= 3

    async def async_setup(self) -> None:
        last_err: Exception | None = None
        for attempt in range(1, SETUP_MAX_RETRIES + 1):
            try:
                _LOGGER.debug(
                    "Setup attempt %d/%d for %s:%s",
                    attempt, SETUP_MAX_RETRIES, self._host, self._port,
                )
                if attempt == 1:
                    await asyncio.sleep(CONFIG_FLOW_GRACE_PERIOD)
                await self._connect_and_load()
                _LOGGER.debug("Setup succeeded on attempt %d", attempt)
                return
            except PanelRefusedError:
                raise
            except (ConnectionError, OSError, asyncio.TimeoutError, UpdateFailed) as err:
                last_err = err
                _LOGGER.debug(
                    "Setup attempt %d failed: %s", attempt, err,
                )
                if attempt < SETUP_MAX_RETRIES:
                    delay = min(
                        SETUP_BACKOFF_BASE ** attempt + random.uniform(0, 1),
                        SETUP_BACKOFF_MAX,
                    )
                    _LOGGER.debug("Retrying in %.1fs", delay)
                    await asyncio.sleep(delay)
        raise last_err  # type: ignore[misc]

    async def _connect_and_load(self, fresh_socket: bool = False) -> None:
        if fresh_socket:
            await self._conn.reconnect()
        else:
            await self._conn.connect()
        await self._do_login()
        await self._do_config()
        if self._metadata_fresh:
            # Names don't change between reconnects; only fetch live state.
            await self._do_status()
        else:
            await self._do_initial_data()
            self._metadata_fresh = True
            if self.on_metadata_updated is not None:
                self.on_metadata_updated()
        self._stage = 3
        self._poll_succeeded()

    async def _do_login(self) -> None:
        result = await self._conn.login(self._password)
        if not result.logged_in:
            err = result.error
            if err == 3:
                raise PanelLoginError("Password rejected by panel")
            raise PanelLoginError(f"Login failed (error={err})")

        self.panel_type = result.panel_type
        self.panel_version = result.panel_version
        self.serial = result.serial
        self.max_zones = result.max_zones
        self.max_areas = result.max_areas
        self.max_rem_outputs = result.max_rem_outputs
        self.part_arm_mask = result.part_arm_mask
        self.user_area = result.user_area
        self.user_number = result.user_number
        _LOGGER.info(
            "Login OK from local UDP port %s: panel=%s max_zones=%d max_areas=%d "
            "user_area=0x%X user=%d",
            self._conn.bound_port, self.panel_type, self.max_zones, self.max_areas,
            self.user_area, self.user_number,
        )

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
        if self.user_area == 0:
            self.user_area = (1 << self.max_areas) - 1
            _LOGGER.warning(
                "user_area was 0 after login, defaulting to all areas: 0x%X",
                self.user_area,
            )

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
        self._apply_status(r)

    async def _do_status(self) -> None:
        r = await self._conn.multi_query([
            (QUERY_SYS_OUTPUT_STATE, 1, 65),
            (CMD_PANEL_STATE, 1, 1),
            (QUERY_ZONE_STATUS, 1, self.max_zones),
        ])
        self._apply_status(r)

    def _apply_status(self, result: ParsedResponse) -> None:
        # A reply without the status block (e.g. an expired login) must not read as all-zero state.
        if not result.has_command(QUERY_SYS_OUTPUT_STATE):
            if result.error is not None:
                self._session_errors += 1
                raise PanelSessionError(
                    f"Panel answered with error {result.error} instead of status data"
                )
            raise PanelInvalidReplyError(
                f"Panel replied without status data (error={result.error})"
            )
        self.sys_output_state = result.sys_output_state
        if result.zone_status:
            self.zone_status = result.zone_status
        self._last_status_at = time.time()

    def export_metadata(self) -> dict[str, Any]:
        data: dict[str, Any] = {f: getattr(self, f) for f in _METADATA_FIELDS}
        data.update({f: list(getattr(self, f)) for f in _METADATA_BYTES_FIELDS})
        return data

    def restore_metadata(self, data: dict[str, Any]) -> None:
        for f in (*_METADATA_FIELDS, *_METADATA_BYTES_FIELDS):
            if f not in data:
                _LOGGER.debug("Cached metadata missing field %s; will refresh from panel", f)
            elif f in _METADATA_BYTES_FIELDS:
                setattr(self, f, bytes(data[f]))
            else:
                setattr(self, f, data[f])

    @callback
    def async_connect_in_background(self) -> None:
        """Start with entities unavailable and keep trying the panel until it answers."""
        self._stage = 0
        self.last_update_success = False
        self._mark_unavailable("startup: waiting for the panel, entities built from cache")
        self._start_reconnect()

    def _backoff_delay(self, attempt: int) -> float:
        if self._last_error_refused:
            delay = min(REFUSED_BACKOFF_BASE * 2 ** (attempt - 1), REFUSED_BACKOFF_MAX)
        else:
            delay = min(RECONNECT_BACKOFF_BASE ** attempt, RECONNECT_BACKOFF_MAX)
        return delay + random.uniform(0, 1)

    async def _reconnect(self) -> None:
        # Each attempt is made because of the outage, then because the previous attempt failed.
        reason = self._last_unavailable_reason or "not connected"
        while True:
            self._reconnect_attempts += 1
            delay = self._backoff_delay(self._reconnect_attempts)
            _LOGGER.debug(
                "Reconnect attempt %d in %.1fs for %s:%s (reason: %s)",
                self._reconnect_attempts, delay, self._host, self._port, reason,
            )
            await asyncio.sleep(delay)
            self._last_reconnect_at = time.time()
            self._last_reconnect_reason = reason
            try:
                # The session is already known to be lost, so don't trust the old socket:
                # rebuild it on the same local port, which the panel still recognises.
                await self._connect_and_load(fresh_socket=True)
                _LOGGER.info(
                    "Reconnected to %s:%s from %s after %d attempts",
                    self._host, self._port, self._conn.local_endpoint,
                    self._reconnect_attempts,
                )
                self._record("reconnected", f"attempt {self._reconnect_attempts}")
                self._reconnect_attempts = 0
                self._last_error_refused = False
                self.async_set_updated_data(self._build_data_dict())
                return
            except (ConnectionError, OSError, asyncio.TimeoutError, UpdateFailed) as err:
                self._last_error_refused = isinstance(err, PanelRefusedError)
                self._last_error = str(err) or type(err).__name__
                reason = describe_failure(err)
                self._record(
                    "reconnect_failed", f"attempt {self._reconnect_attempts}: {reason}"
                )
                if isinstance(err, PanelRefusedError):
                    _LOGGER.warning(
                        "%s; backing off before attempt %d",
                        err, self._reconnect_attempts + 1,
                    )
                elif isinstance(err, LocalPortInUseError):
                    _LOGGER.warning(
                        "Reconnect attempt %d failed: %s", self._reconnect_attempts, err,
                    )
                else:
                    _LOGGER.debug(
                        "Reconnect attempt %d failed: %s", self._reconnect_attempts, reason,
                    )
                # HA only notifies entities when a poll's outcome changes, so the Panel Info
                # sensor wouldn't otherwise show how the outage is going.
                self.async_update_listeners()

    def _start_reconnect(self) -> None:
        if self._reconnect_task is not None and not self._reconnect_task.done():
            return
        self._reconnect_task = self.hass.async_create_task(
            self._reconnect(), f"orisec_reconnect_{self._host}"
        )

    def _cancel_reconnect(self) -> None:
        if self._reconnect_task is not None and not self._reconnect_task.done():
            self._reconnect_task.cancel()
            self._reconnect_task = None

    def _build_data_dict(self) -> dict[str, Any]:
        return {
            "sys_output_state": self.sys_output_state,
            "zone_status": self.zone_status,
            "zone_timers": self.zone_timers,
            "zone_bypass": self.zone_bypass,
            "rem_output_state": self.rem_output_state,
        }

    async def _async_update_data(self) -> dict[str, Any]:
        self._polls += 1
        self._last_poll_at = time.time()
        if not self.connected:
            if self._reconnect_task is None or self._reconnect_task.done():
                self._start_reconnect()
            raise UpdateFailed(
                f"Not connected to panel at {self._host}:{self._port}, "
                f"reconnect attempt {self._reconnect_attempts} in progress"
            )

        try:
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
            self._apply_status(result)

            if self._consecutive_failures:
                self._record(
                    "state_confirmed", f"after {self._consecutive_failures} failed poll(s)"
                )
            self._poll_succeeded()
            self._reconnect_attempts = 0
            if result.zone_timers:
                self.zone_timers = result.zone_timers
            if result.zone_bypass:
                self.zone_bypass = result.zone_bypass
            if result.rem_output_state:
                self.rem_output_state = result.rem_output_state

            if self._keypad_subscribers > 0 and result.lcd_raw:
                self._panel_time = result.panel_time[:]
                if result.lcd_raw != self._lcd_raw:
                    self._lcd_raw = result.lcd_raw
                    self._notify_lcd_subscribers()

            self._check_alarm_events()
            self._notify_panel_subscribers()

            return self._build_data_dict()

        except Exception as err:
            self._consecutive_failures += 1
            self._last_error = str(err) or type(err).__name__
            # A refusal or an error reply means the session is gone; anything else
            # (lost datagrams) is ridden out on the last known state for a while.
            session_lost = isinstance(err, (PanelRefusedError, PanelSessionError))
            silent_for = time.monotonic() - self._last_poll_ok
            if not session_lost and silent_for < POLL_FAILURE_GRACE:
                if self._consecutive_failures == 1:
                    self._record("state_unconfirmed", describe_failure(err))
                _THROTTLED.debug(
                    "poll_failed",
                    "Poll failed (%d in a row, %.0fs since last good poll), "
                    "keeping last state: %s",
                    self._consecutive_failures, silent_for, describe_failure(err),
                )
                return self._build_data_dict()
            self._stage = 0
            self._connection_drops += 1
            self._last_error_refused = isinstance(err, PanelRefusedError)
            if session_lost:
                reason = describe_failure(err)
            else:
                reason = (
                    f"{failure_category(err)}: no good poll for {silent_for:.0f}s "
                    f"({self._consecutive_failures} failed in a row); last error: "
                    f"{err or type(err).__name__}"
                )
            self._mark_unavailable(reason)
            _LOGGER.info(
                "Marking panel at %s:%s unavailable and reconnecting: %s",
                self._host, self._port, reason,
            )
            self._start_reconnect()
            if isinstance(err, UpdateFailed):
                raise
            raise UpdateFailed(f"Communication error: {err}") from err

    def _not_connected_message(self) -> str:
        msg = f"Not connected to panel at {self._host}:{self._port}"
        if self._last_error:
            msg += f" (last error: {self._last_error})"
        return msg

    def _poll_succeeded(self) -> None:
        self._last_poll_ok = time.monotonic()
        self._consecutive_failures = 0

    def _mark_unavailable(self, reason: str) -> None:
        self._last_unavailable_at = time.time()
        self._last_unavailable_reason = reason
        self._record("unavailable", reason)

    def _record(self, event: str, detail: str) -> None:
        self._history.append({"at": time.time(), "event": event, "detail": detail})

    @property
    def connection_status(self) -> str:
        """connected, degraded (riding out failed polls on cached state), reconnecting or disconnected."""
        if self.connected:
            return "degraded" if self._consecutive_failures else "connected"
        if self._reconnect_task is not None and not self._reconnect_task.done():
            return "reconnecting"
        return "disconnected"

    @property
    def state_confirmed(self) -> bool:
        """True when entity state comes from the latest poll, not from a cached earlier reply."""
        return self.connection_status == "connected"

    @property
    def state_cached_since(self) -> str | None:
        """When the panel last confirmed the state being shown, if it isn't confirmed now."""
        if self.state_confirmed:
            return None
        return _timestamp(self._last_status_at)

    @property
    def connection_stats(self) -> dict[str, Any]:
        """Entity attributes for diagnosing an unreliable link.

        Kept to values that change only when something goes wrong, so a healthy link
        doesn't write a new state on every poll; see diagnostics() for the rest.
        """
        return {
            "status": self.connection_status,
            "state_confirmed": self.state_confirmed,
            "state_cached_since": self.state_cached_since,
            "local_endpoint": self._conn.local_endpoint,
            "remote_endpoint": self._conn.remote_endpoint,
            # Should equal the expected port whenever connected; None while disconnected.
            "local_port": self._conn.bound_port,
            "expected_local_port": self._conn.local_port,
            **self._conn.stats,
            "consecutive_timeouts": self._conn.consecutive_timeouts,
            "session_errors": self._session_errors,
            "reconnect_attempts": self._reconnect_attempts,
            "connection_drops": self._connection_drops,
            "consecutive_failures": self._consecutive_failures,
            "last_error": self._last_error,
            "last_unavailable_at": _timestamp(self._last_unavailable_at),
            "last_unavailable_reason": self._last_unavailable_reason,
            "last_reconnect_at": _timestamp(self._last_reconnect_at),
            "last_reconnect_reason": self._last_reconnect_reason,
        }

    def diagnostics(self) -> dict[str, Any]:
        """Everything known about the link, for the diagnostics download. Holds no PIN."""
        conn = self._conn
        response_time = conn.last_response_time
        return {
            "status": self.connection_status,
            "entities_available": self.last_update_success,
            "state_confirmed": self.state_confirmed,
            "state_cached_since": self.state_cached_since,
            "stage": self._stage,
            "metadata_source": "panel" if self._metadata_fresh else "cache",
            "endpoints": {
                "local": conn.local_endpoint,
                "remote": conn.remote_endpoint,
                "expected_local_port": conn.local_port,
            },
            "timestamps": {
                # The coordinator asked for data (stops moving if polling has stopped).
                "last_poll_started": _timestamp(self._last_poll_at),
                # A datagram went out (stops moving if nothing is being sent).
                "last_request_sent": _timestamp(conn.last_request_at),
                # Any usable reply came back (last successful communication).
                "last_reply_received": _timestamp(conn.last_reply_at),
                # The panel's status was read and applied (last confirmed panel state).
                "last_confirmed_state": _timestamp(self._last_status_at),
                "last_unavailable": _timestamp(self._last_unavailable_at),
                "last_reconnect_attempt": _timestamp(self._last_reconnect_at),
            },
            "counters": {
                "polls": self._polls,
                **conn.traffic,
                **conn.stats,
                "consecutive_timeouts": conn.consecutive_timeouts,
                "consecutive_failed_polls": self._consecutive_failures,
                "session_errors": self._session_errors,
                "connection_drops": self._connection_drops,
                "reconnect_attempts": self._reconnect_attempts,
            },
            "last_response_time_ms": (
                None if response_time is None else round(response_time * 1000)
            ),
            "last_error": self._last_error,
            "last_udp_error": conn.last_udp_error,
            "last_unavailable_reason": self._last_unavailable_reason,
            "last_reconnect_reason": self._last_reconnect_reason,
            "settings": {
                "poll_interval_s": self.update_interval.total_seconds(),
                "udp_timeout_s": UDP_TIMEOUT,
                "command_timeout_s": COMMAND_TIMEOUT,
                "poll_failure_grace_s": POLL_FAILURE_GRACE,
            },
            "history": [
                {**entry, "at": _timestamp(entry["at"])} for entry in self._history
            ],
        }

    @callback
    def _check_alarm_events(self) -> None:
        sos = self.sys_output_state
        now = datetime.now().isoformat(timespec="seconds")
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
                event_data = {
                    "area": area_idx + 1,
                    "area_name": area_name,
                    "fire": bool(sos[SOS_FIRE] & bit),
                    "pa": bool(sos[SOS_PA] & bit),
                    "bell": bool(sos[SOS_BELL] & bit),
                }
                self.hass.bus.async_fire(f"{DOMAIN}_alarm_triggered", event_data)
                self._append_event("alarm_triggered", area_name, event_data, now)
            elif prev_alarm and not in_alarm:
                event_data = {
                    "area": area_idx + 1,
                    "area_name": area_name,
                }
                self.hass.bus.async_fire(f"{DOMAIN}_alarm_cleared", event_data)
                self._append_event("alarm_cleared", area_name, event_data, now)
            self._prev_alarm_state[area_idx] = in_alarm

            current_state = self.get_alarm_state_for_area(area_idx)
            prev_state = self._prev_arm_state.get(area_idx)
            if prev_state is not None and current_state != prev_state:
                event_data = {
                    "area": area_idx + 1,
                    "area_name": area_name,
                    "old_state": prev_state,
                    "new_state": current_state,
                }
                self.hass.bus.async_fire(f"{DOMAIN}_state_changed", event_data)
                self._append_event("state_changed", area_name, event_data, now)
            self._prev_arm_state[area_idx] = current_state

    def _append_event(
        self, event_type: str, area_name: str, data: dict, timestamp: str
    ) -> None:
        self._event_log.append({
            "type": event_type,
            "area_name": area_name,
            "data": data,
            "timestamp": timestamp,
        })
        if len(self._event_log) > 20:
            self._event_log = self._event_log[-20:]

    async def _login_for_command(self) -> None:
        # The panel has one login shared by every client, and status polls keep working without
        # ours. Since connecting, the app may have logged in as another user or the session may
        # have lapsed, so commands would run under someone else's session or none.
        try:
            result = await self._conn.login(self._password)
        except ConnectionError as err:
            raise HomeAssistantError(
                f"Could not log in to the alarm panel, so the command was not sent: {err}"
            ) from err
        if not result.logged_in:
            raise HomeAssistantError(
                "The alarm panel refused the login "
                f"({_describe_panel_error(result.error)}), so the command was not sent"
            )

    async def async_send_keypress(self, key_code: int, area_mask: int) -> None:
        # Not just the socket: an open socket without a logged-in session must not send keys.
        if not self.connected:
            raise ConnectionError(self._not_connected_message())
        await self._login_for_command()
        try:
            result = await self._conn.send_keypress(key_code, area_mask)
        except PanelNoResponseError as err:
            # Sent once only: the ack may be what got lost, so re-read rather than resend.
            await self.async_request_refresh()
            raise HomeAssistantError(
                "The alarm panel did not acknowledge the command. It may still have "
                "been applied; check the alarm state before trying again."
            ) from err
        if result.error is not None:
            raise HomeAssistantError(
                "The alarm panel rejected the command "
                f"({_describe_panel_error(result.error)})"
            )
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
        if not self.connected:
            raise ConnectionError(self._not_connected_message())
        current = 0
        if output_index < len(self.rem_output_state):
            current = self.rem_output_state[output_index]
        await self._login_for_command()
        try:
            result = await self._conn.toggle_output(output_index, current)
        except PanelNoResponseError as err:
            await self.async_request_refresh()
            raise HomeAssistantError(
                "The alarm panel did not acknowledge the output change. It may still "
                "have been applied; check the output state before trying again."
            ) from err
        if result.error is not None:
            raise HomeAssistantError(
                "The alarm panel rejected the output change "
                f"({_describe_panel_error(result.error)})"
            )
        await asyncio.sleep(0.3)
        r = await self._conn.query(
            QUERY_REM_OUTPUT_STATE, 1, self.max_rem_outputs + 1
        )
        if r.rem_output_state:
            self.rem_output_state = r.rem_output_state
        await self.async_request_refresh()

    async def async_shutdown(self) -> None:
        self._cancel_reconnect()
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
        return bool(self.sys_output_state[SOS_READY] & (1 << area_idx))

    # ── Keypad / LCD ────────────────────────────────────────────────────────

    _VALID_KEYPAD_CHARS = frozenset("0123456789FPAYNOCRludr ")

    def keypad_subscribe(self, send_callback: Callable) -> Callable:
        self._keypad_subscribers += 1
        self._lcd_callbacks.append(send_callback)
        self.update_interval = timedelta(seconds=KEYPAD_POLL_INTERVAL)
        send_callback(self._get_lcd_state())

        def unsubscribe() -> None:
            self._keypad_subscribers = max(0, self._keypad_subscribers - 1)
            if send_callback in self._lcd_callbacks:
                self._lcd_callbacks.remove(send_callback)
            if self._keypad_subscribers == 0:
                self.update_interval = timedelta(seconds=POLL_INTERVAL)

        return unsubscribe

    def _get_lcd_state(self) -> dict:
        return {
            "lcd_raw": list(self._lcd_raw),
            "time": self._panel_time[:],
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
        if not self.connected:
            raise ConnectionError(self._not_connected_message())
        if len(char) != 1 or char not in self._VALID_KEYPAD_CHARS:
            raise ValueError(f"Invalid keypad character: {char!r}")
        await self._conn.send_keypad_char(char)
        if self._keypad_subscribers > 0:
            await self.async_request_refresh()

    # ── Panel state subscription ────────────────────────────────────────────

    def panel_subscribe(self, send_callback: Callable) -> Callable:
        self._panel_callbacks.append(send_callback)
        send_callback(self.get_panel_state())

        def unsubscribe() -> None:
            if send_callback in self._panel_callbacks:
                self._panel_callbacks.remove(send_callback)

        return unsubscribe

    def get_panel_state(self) -> dict:
        sos = self.sys_output_state
        areas = []
        for area_idx in range(self.max_areas):
            bit = 1 << area_idx
            area_name = (
                self.area_names[area_idx]
                if area_idx < len(self.area_names) and self.area_names[area_idx]
                else f"Area {area_idx + 1}"
            )
            areas.append({
                "name": area_name,
                "state": self.get_alarm_state_for_area(area_idx),
                "ready": bool(sos[SOS_READY] & bit),
                "trouble": bool(sos[SOS_TROUBLE] & bit),
                "bypass": bool(sos[SOS_BYPASS] & bit),
                "bell": bool(sos[SOS_BELL] & bit),
                "in_alarm": bool(sos[SOS_ALARM] & bit) or bool(sos[SOS_IN_ALARM] & bit),
                "in_entry": bool(sos[SOS_IN_ENTRY] & bit),
                "in_exit": bool(sos[SOS_IN_EXIT] & bit),
            })
        return {
            "areas": areas,
            "part_arm_names": self.part_arm_names[:],
            "part_arm_mask": self.part_arm_mask,
            "ac_power": bool(sos[SOS_PANEL_AC_ON] & 0xFF) if len(sos) > SOS_PANEL_AC_ON else True,
            "battery_fault": bool(sos[SOS_BATTERY_FAULT] & 0xFF) if len(sos) > SOS_BATTERY_FAULT else False,
            "panel_type": self.panel_type,
            "panel_version": self.panel_version,
            "connected": self.connected,
            "events": self._event_log[:],
        }

    def get_event_log(self) -> list[dict]:
        return self._event_log[:]

    @callback
    def _notify_panel_subscribers(self) -> None:
        if not self._panel_callbacks:
            return
        state = self.get_panel_state()
        for cb in self._panel_callbacks[:]:
            try:
                cb(state)
            except Exception:
                _LOGGER.debug("Error notifying panel subscriber", exc_info=True)
