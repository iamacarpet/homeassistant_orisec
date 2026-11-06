"""Async UDP protocol for Orisec ControlPlus2 panels."""

from __future__ import annotations

import asyncio
import errno
import logging
import struct
import time
import zlib
from dataclasses import dataclass, field
from typing import Any

from .const import (
    CMD_CONTROL_OUTPUT,
    COMMAND_TIMEOUT,
    CMD_ERROR,
    CMD_KEYPAD_CHAR,
    CMD_KEYPRESS,
    CMD_LCD,
    CMD_PANEL_INFO,
    CMD_PANEL_STATE,
    CMD_PASSWORD,
    CMD_SYS_CONFIG,
    CRC16_INIT,
    CRC16_TABLE,
    LOCAL_PORT_BASE,
    LOCAL_PORT_RANGE,
    PANEL_TYPE_MAP,
    QUERY_AREA_ARM_ATT,
    QUERY_AREA_ARM_MODE,
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
    QUERY_ZONE_AREAS,
    QUERY_ZONE_BYPASS,
    QUERY_ZONE_STATUS,
    QUERY_ZONE_TEXTS,
    QUERY_ZONE_TIMERS,
    QUERY_ZONE_TYPES,
    QUERY_ZONE_WIRING,
    QUERY_SYS_OUTPUT_STATE,
    QUERY_SYS_TEXT,
    QUERY_MAX_SYS_TEXT,
    QUERY_UDL_OPTION,
    QUERY_USER_TYPE,
    QUERY_ZONE_STATUS2,
    SEND_RETRIES,
    UDP_TIMEOUT,
)
from .throttled_log import ThrottledLog

_LOGGER = logging.getLogger(__name__)
_THROTTLED = ThrottledLog(_LOGGER)


def calc_crc16(data: bytes | bytearray, count: int) -> int:
    crc = CRC16_INIT
    for i in range(count):
        crc = CRC16_TABLE[(data[i] ^ crc) & 0xFF] ^ (crc >> 8)
    return crc & 0xFFFF


def _add_checksum(buf: bytearray) -> None:
    total_len = struct.unpack_from("<H", buf, 0)[0]
    crc_offset = total_len - 2
    if crc_offset < 2:
        return
    crc = calc_crc16(buf, crc_offset)
    struct.pack_into("<H", buf, crc_offset, crc)


def load_udl_pkt(cmd: int, start: int, count: int) -> bytearray:
    buf = bytearray(200)
    struct.pack_into("<H", buf, 0, 12)
    struct.pack_into("<H", buf, 2, cmd)
    struct.pack_into("<H", buf, 4, start)
    struct.pack_into("<H", buf, 6, count)
    struct.pack_into("<H", buf, 8, 0)
    _add_checksum(buf)
    return buf


def add_udl_pkt(buf: bytearray, cmd: int, start: int, count: int) -> bytearray:
    total_len = struct.unpack_from("<H", buf, 0)[0]
    needed = total_len + 8
    if len(buf) < needed:
        buf.extend(b"\x00" * (needed - len(buf)))
    pos = total_len - 4 if total_len > 4 else 0
    struct.pack_into("<H", buf, pos + 2, cmd)
    struct.pack_into("<H", buf, pos + 4, start)
    struct.pack_into("<H", buf, pos + 6, count)
    struct.pack_into("<H", buf, pos + 8, 0)
    new_len = total_len + 8
    buf[0] = new_len & 0xFF
    buf[1] = (new_len >> 8) & 0xFF
    _add_checksum(buf)
    return buf


def load_data_pkt(cmd: int, start: int, count: int, message: bytes) -> bytearray:
    total_len = len(message) + 12
    buf = bytearray(total_len)
    struct.pack_into("<H", buf, 0, total_len)
    struct.pack_into("<H", buf, 2, cmd)
    struct.pack_into("<H", buf, 4, start)
    struct.pack_into("<H", buf, 6, count)
    struct.pack_into("<H", buf, 8, len(message))
    buf[10 : 10 + len(message)] = message
    _add_checksum(buf)
    return buf


def build_password_packet(password: str) -> bytearray:
    buf = load_udl_pkt(CMD_PASSWORD, 1, 1)
    pw_bytes = password.encode("ascii")
    buf[8] = len(pw_bytes)
    new_len = 12 + len(pw_bytes)
    buf[0] = new_len & 0xFF
    buf[1] = (new_len >> 8) & 0xFF
    for i, b in enumerate(pw_bytes):
        buf[10 + i] = b
    _add_checksum(buf)
    return buf


def build_login_packet(password: str) -> bytearray:
    buf = build_password_packet(password)
    buf = add_udl_pkt(buf, CMD_PANEL_INFO, 1, 1)
    buf = add_udl_pkt(buf, CMD_PANEL_STATE, 1, 1)
    buf = add_udl_pkt(buf, CMD_SYS_CONFIG, 1, 1)
    return buf


def build_keypress_packet(key_code: int, area_mask: int) -> bytearray:
    data = bytes([
        key_code,
        area_mask & 0xFF,
        (area_mask >> 8) & 0xFF,
        (area_mask >> 16) & 0xFF,
    ])
    return load_data_pkt(CMD_KEYPRESS, 1, 1, data)


def build_output_toggle_packet(output_index: int, current_state: int) -> bytearray:
    output_id = 2000 + output_index
    new_state = current_state ^ 1
    data = bytes([
        output_id & 0xFF,
        (output_id >> 8) & 0xFF,
        new_state,
        2,
    ])
    return load_data_pkt(CMD_CONTROL_OUTPUT, 1, 1, data)


def build_keypad_char_packet(char: str) -> bytearray:
    data = char.encode("ascii")
    return load_data_pkt(CMD_KEYPAD_CHAR, 1, 1, data)


def trim_packet(buf: bytearray) -> bytes:
    total_len = struct.unpack_from("<H", buf, 0)[0]
    return bytes(buf[:total_len])


def packet_commands(data: bytes) -> list[int]:
    """Command IDs of the blocks in a request or reply packet (both share the block layout)."""
    if len(data) < 4:
        return []
    end = min(struct.unpack_from("<H", data, 0)[0] - 2, len(data))
    pos = 2
    cmds: list[int] = []
    while pos + 8 <= end:
        cmds.append(struct.unpack_from("<H", data, pos)[0])
        pos += 8 + struct.unpack_from("<H", data, pos + 6)[0]
    return cmds


def crc_valid(data: bytes) -> bool:
    if len(data) < 4:
        return False
    total_len = struct.unpack_from("<H", data, 0)[0]
    if total_len < 4 or total_len > len(data):
        return False
    stored = struct.unpack_from("<H", data, total_len - 2)[0]
    return stored == calc_crc16(data, total_len - 2)


@dataclass
class ParsedResponse:
    logged_in: bool = False
    error: int | None = None
    panel_type: str | None = None
    panel_version: str | None = None
    panel_id: int | None = None
    panel_var: int | None = None
    serial: str | None = None
    max_zones: int = 0
    max_areas: int = 0
    max_rem_outputs: int = 0
    part_arm_mask: int = 7
    user_number: int = 0
    user_area: int = 0
    log_ptr: int = 0
    sys_output_state: list[int] = field(default_factory=lambda: [0] * 100)
    zone_types: bytes = b""
    zone_types_start: int = 1
    zone_status: bytes = b""
    zone_status_start: int = 1
    zone_status_item_size: int = 2
    zone_timers: bytes = b""
    zone_timers_start: int = 1
    zone_names: list[str] = field(default_factory=list)
    zone_areas: bytes = b""
    zone_bypass: bytes = b""
    area_names: list[str] = field(default_factory=list)
    area_arm_mode: bytes = b""
    rem_output_state: bytes = b""
    rem_output_start: int = 1
    rem_output_item_size: int = 1
    rem_output_names: list[str] = field(default_factory=list)
    part_arm_names: list[str] = field(default_factory=list)
    user_type: int = -1
    lcd_raw: bytes = b""
    panel_time: list[int] = field(default_factory=lambda: [0, 0, 0])
    commands: list[dict[str, Any]] = field(default_factory=list)

    def has_command(self, cmd: int) -> bool:
        return any(c["cmd"] == cmd for c in self.commands)


def _parse_null_terminated_strings(payload: bytes, data_len: int) -> list[str]:
    names: list[str] = []
    offset = 0
    while offset < data_len:
        end = payload.find(0, offset)
        if end < 0:
            end = data_len
        names.append(payload[offset:end].decode("ascii", errors="replace"))
        offset = end + 1
    return names


def parse_response(data: bytes, result: ParsedResponse | None = None) -> ParsedResponse:
    if result is None:
        result = ParsedResponse()

    if len(data) < 4:
        return result

    total_len = struct.unpack_from("<H", data, 0)[0]
    end = total_len - 2
    pos = 2

    while pos < end and pos + 8 <= len(data):
        cmd = struct.unpack_from("<H", data, pos)[0]
        start_idx = struct.unpack_from("<H", data, pos + 2)[0]
        item_size = struct.unpack_from("<H", data, pos + 4)[0]
        data_len = struct.unpack_from("<H", data, pos + 6)[0]
        pos += 8

        items_count = 0
        if item_size > 0 and data_len > 0:
            items_count = data_len // item_size

        payload = data[pos : pos + data_len] if data_len > 0 else b""

        result.commands.append({
            "cmd": cmd,
            "start": start_idx,
            "item_size": item_size,
            "data_len": data_len,
        })

        if cmd == CMD_PASSWORD:
            if data_len == 0:
                result.logged_in = True
            else:
                result.error = payload[0] if payload else -1

        elif cmd == CMD_ERROR:
            result.error = payload[0] if payload else -1

        elif cmd == CMD_PANEL_INFO and data_len > 0:
            result.panel_version = f"{payload[0]}.{payload[1]:02d}"
            result.panel_id = payload[5] & 0xFF
            result.panel_var = payload[4] & 0xFF
            panel_type = PANEL_TYPE_MAP.get(result.panel_id, f"CP{result.panel_id}")
            if (
                result.panel_var == 1
                and result.panel_id not in (40, 200)
                and panel_type.startswith("CP")
            ):
                panel_type = "Z" + panel_type[1:]
            elif (
                result.panel_var == 1
                and result.panel_id not in (40, 200)
                and panel_type.startswith("EP")
            ):
                panel_type = "Z" + panel_type[1:]
            result.panel_type = panel_type

        elif cmd == CMD_PANEL_STATE and data_len > 0:
            result.log_ptr = (
                struct.unpack_from("<H", payload, 2)[0] if len(payload) > 3 else 0
            )
            result.user_number = (
                struct.unpack_from("<H", payload, 6)[0] if len(payload) > 7 else 0
            )
            if data_len > 14:
                result.user_area = (
                    struct.unpack_from("<I", payload, 8)[0]
                    if len(payload) > 11
                    else 0
                )
            else:
                result.user_area = (
                    struct.unpack_from("<H", payload, 8)[0]
                    if len(payload) > 9
                    else 0
                )

        elif cmd == CMD_SYS_CONFIG and data_len > 0:
            if not result.logged_in:
                pos += data_len
                continue
            i = 0
            while i + 1 < data_len:
                sub_cmd = payload[i]
                sub_len = payload[i + 1]
                sub_data = payload[i + 2 : i + 2 + sub_len]
                i += sub_len + 2
                if sub_cmd == 90 and sub_data:
                    result.max_zones = sub_data[0]
                elif sub_cmd == 65 and sub_data:
                    result.max_areas = sub_data[0]
                elif sub_cmd == 83 and sub_data:
                    result.serial = sub_data.decode(
                        "ascii", errors="replace"
                    ).rstrip("\x00")
                elif sub_cmd == 86 and sub_data:
                    result.max_rem_outputs = sub_data[0] if len(sub_data) > 0 else 0
                    result.part_arm_mask = sub_data[2] if len(sub_data) > 2 else 0

        elif cmd == CMD_SYS_CONFIG and data_len == 0:
            result.part_arm_mask = 7

        elif cmd == QUERY_SYS_OUTPUT_STATE and data_len > 0:
            for i in range(min(data_len, 65)):
                result.sys_output_state[start_idx - 1 + i] = payload[i]

        elif cmd == QUERY_ZONE_TYPES and data_len > 0:
            result.zone_types = payload
            result.zone_types_start = start_idx

        elif cmd == QUERY_ZONE_STATUS and data_len > 0:
            result.zone_status = payload
            result.zone_status_start = start_idx
            result.zone_status_item_size = 2 if data_len >= items_count * 2 else 1

        elif cmd == QUERY_ZONE_TIMERS and data_len > 0:
            result.zone_timers = payload
            result.zone_timers_start = start_idx

        elif cmd == QUERY_ZONE_TEXTS and data_len > 0:
            names = _parse_null_terminated_strings(payload, data_len)
            if start_idx == 1:
                result.zone_names = names
            else:
                while len(result.zone_names) < start_idx - 1:
                    result.zone_names.append("")
                result.zone_names.extend(names)

        elif cmd == QUERY_ZONE_AREAS and data_len > 0:
            result.zone_areas = payload

        elif cmd == QUERY_ZONE_BYPASS and data_len > 0:
            result.zone_bypass = payload

        elif cmd == QUERY_AREA_TEXTS and data_len > 0:
            result.area_names = _parse_null_terminated_strings(payload, data_len)

        elif cmd == QUERY_AREA_ARM_MODE and data_len > 0:
            result.area_arm_mode = payload

        elif cmd == QUERY_REM_OUTPUT_STATE and data_len > 0:
            result.rem_output_state = payload
            result.rem_output_start = start_idx
            result.rem_output_item_size = item_size if item_size > 0 else 1

        elif cmd == QUERY_REM_OUTPUT_TEXTS and data_len > 0:
            result.rem_output_names = _parse_null_terminated_strings(
                payload, data_len
            )

        elif cmd == QUERY_PART_ARM_TEXTS and data_len > 0:
            result.part_arm_names = _parse_null_terminated_strings(payload, data_len)

        elif cmd == QUERY_USER_TYPE and data_len > 0:
            result.user_type = payload[0] if payload else -1

        elif cmd == CMD_LCD and data_len > 0:
            result.lcd_raw = bytes(payload[:data_len])

        elif cmd == QUERY_PANEL_TIME_H and data_len > 0:
            result.panel_time[0] = payload[0]

        elif cmd == QUERY_PANEL_TIME_M and data_len > 0:
            result.panel_time[1] = payload[0]

        elif cmd == QUERY_PANEL_TIME_S and data_len > 0:
            result.panel_time[2] = payload[0]

        pos += data_len

    return result


def parse_responses(
    responses: list[bytes], result: ParsedResponse | None = None
) -> ParsedResponse:
    if result is None:
        result = ParsedResponse()
    for data in responses:
        parse_response(data, result)
    return result


class PanelRefusedError(ConnectionError):
    """The panel answered with ICMP port-unreachable; retrying quickly won't help."""


class PanelNoResponseError(ConnectionError):
    """The panel never answered a request, even after retries."""


class PanelUDPError(ConnectionError):
    """The host's network stack reported an error for our datagrams (other than a refusal)."""


class LocalPortInUseError(ConnectionError):
    """The fixed local UDP port is held by another socket, so the panel can't be reached from it."""


class OrisecUDPProtocol(asyncio.DatagramProtocol):

    def __init__(self) -> None:
        self.responses: list[bytes] = []
        self.event = asyncio.Event()
        self.transport: asyncio.DatagramTransport | None = None
        self.error: Exception | None = None
        # Set once the OS socket is really closed and its local port is free again.
        self.closed = asyncio.Event()

    def connection_made(self, transport: asyncio.DatagramTransport) -> None:  # type: ignore[override]
        self.transport = transport

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:  # type: ignore[override]
        self.responses.append(data)
        self.event.set()

    def error_received(self, exc: Exception) -> None:
        _THROTTLED.debug("udp_error_received", "UDP error: %s", exc)
        self.error = exc
        self.event.set()

    def connection_lost(self, exc: Exception | None) -> None:
        self.closed.set()


def _format_endpoint(addr: Any) -> str:
    return f"{addr[0]}:{addr[1]}"


def local_port_for(host: str, port: int) -> int:
    return LOCAL_PORT_BASE + zlib.crc32(f"{host}:{port}".encode()) % LOCAL_PORT_RANGE


class OrisecConnection:

    def __init__(
        self,
        host: str,
        port: int,
        timeout: float = UDP_TIMEOUT,
        command_timeout: float = COMMAND_TIMEOUT,
    ) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.command_timeout = command_timeout
        # One source port per panel, kept across reconnects and restarts. The CP20 answers any
        # endpoint, but older reports had the panel refusing a client whose endpoint changed.
        self.local_port = local_port_for(host, port)
        self._transport: asyncio.DatagramTransport | None = None
        self._protocol: OrisecUDPProtocol | None = None
        # Replies carry no request id, so only one request may be in flight at a time.
        self._lock = asyncio.Lock()
        # Only enforce reply CRCs once the panel has been seen to send valid ones.
        self._crc_trusted = False
        # Problem counters: these only move when something goes wrong.
        self.stats: dict[str, int] = {
            "bind_failures": 0,
            # Requests that got no usable reply, after all their attempts.
            "failed_requests": 0,
            # Attempts that got no usable reply within the timeout (dropped replies don't count).
            "timeouts": 0,
            "retries": 0,
            "refused": 0,
            # Errors other than a refusal reported by the host for our datagrams.
            "udp_errors": 0,
            # Replies that answered no request in flight (late, or for another request).
            "stale_replies_dropped": 0,
            "corrupt_replies_dropped": 0,
        }
        # Traffic totals: these rise on every poll.
        self.traffic: dict[str, int] = {
            # Requests made; a retried request counts once.
            "requests": 0,
            # Datagrams sent, including retries.
            "packets_sent": 0,
            # Datagrams accepted as replies.
            "replies_received": 0,
        }
        # Attempts in a row without a usable reply; reset by any accepted reply.
        self.consecutive_timeouts = 0
        # Wall-clock times (time.time()) for diagnostics.
        self.last_request_at: float | None = None
        self.last_reply_at: float | None = None
        # From sending a request to its first accepted reply.
        self.last_response_time: float | None = None
        self.last_udp_error: str | None = None

    async def connect(self) -> None:
        if self.connected:
            return
        # A socket still closing holds the fixed port; binding now would fall back to a random one.
        await self._wait_closed()
        loop = asyncio.get_running_loop()
        try:
            self._transport, self._protocol = await loop.create_datagram_endpoint(
                OrisecUDPProtocol,
                local_addr=("0.0.0.0", self.local_port),
                remote_addr=(self.host, self.port),
            )
        except OSError as err:
            if err.errno != errno.EADDRINUSE:
                raise
            # No random-port fallback: the port is only ever held by another client of this
            # panel on this host, and two clients polling it at once take each other's replies.
            self.stats["bind_failures"] += 1
            raise LocalPortInUseError(
                f"Local UDP port {self.local_port} (used to reach {self.host}:{self.port}) "
                "is already in use by another socket, e.g. another Home Assistant "
                "instance or config entry talking to the same panel"
            ) from err
        _LOGGER.debug("UDP socket %s -> %s", self.local_endpoint, self.remote_endpoint)

    async def disconnect(self) -> None:
        if self._transport is not None:
            self._transport.close()
            await self._wait_closed()
            self._transport = None
            self._protocol = None

    async def reconnect(self) -> None:
        """Replace the socket with a fresh one bound to the same local port.

        The panel sees the same client endpoint, but any state stuck on the old socket
        (e.g. a source address cached before the host's IP changed) is dropped.
        """
        async with self._lock:
            await self.disconnect()
            await self.connect()

    async def _wait_closed(self) -> None:
        # transport.close() only releases the socket on a later loop iteration.
        if self._transport is None or self._protocol is None:
            return
        try:
            await asyncio.wait_for(self._protocol.closed.wait(), 1.0)
        except asyncio.TimeoutError:
            _LOGGER.debug("UDP socket to %s:%s did not report closing", self.host, self.port)

    @property
    def connected(self) -> bool:
        return self._transport is not None and not self._transport.is_closing()

    @property
    def bound_port(self) -> int | None:
        """The local UDP port the open socket is actually bound to, if any."""
        if not self.connected:
            return None
        return self._transport.get_extra_info("sockname")[1]

    @property
    def local_endpoint(self) -> str | None:
        """The open socket's source address as ``ip:port`` (the IP the OS routes from)."""
        if not self.connected:
            return None
        return _format_endpoint(self._transport.get_extra_info("sockname"))

    @property
    def remote_endpoint(self) -> str:
        """The panel address the socket sends to."""
        if self.connected:
            peer = self._transport.get_extra_info("peername")
            if peer:
                return _format_endpoint(peer)
        return f"{self.host}:{self.port}"

    async def send_receive(
        self,
        packet: bytearray | bytes,
        settle_time: float = 0.2,
        retries: int = SEND_RETRIES,
        match_commands: bool = True,
        timeout: float | None = None,
    ) -> list[bytes]:
        async with self._lock:
            if self._transport is None or self._protocol is None:
                raise ConnectionError("Not connected")
            self.traffic["requests"] += 1
            try:
                return await self._send_receive(
                    packet, settle_time, retries, match_commands,
                    self.timeout if timeout is None else timeout,
                )
            except Exception:
                self.stats["failed_requests"] += 1
                raise

    async def _send_receive(
        self,
        packet: bytearray | bytes,
        settle_time: float,
        retries: int,
        match_commands: bool,
        timeout: float,
    ) -> list[bytes]:
        assert self._transport is not None and self._protocol is not None
        data = trim_packet(bytearray(packet))
        # None accepts any well-formed reply, for requests whose reply format is unknown.
        expected = set(packet_commands(data)) if match_commands else None

        # Only command IDs are ever logged: request payloads carry the PIN and key presses.
        commands = sorted(packet_commands(data))
        last_error: Exception | None = None
        for attempt in range(1, retries + 1):
            if attempt > 1:
                self.stats["retries"] += 1
            self._discard_unclaimed_replies()
            self._protocol.event.clear()
            self._protocol.error = None

            loop = asyncio.get_running_loop()
            sent_at = loop.time()
            self.last_request_at = time.time()
            self.traffic["packets_sent"] += 1
            self._transport.sendto(data)
            replies, first_reply_at = await self._collect_replies(
                expected, settle_time, timeout
            )
            if replies:
                self.last_response_time = first_reply_at - sent_at
                _THROTTLED.debug(
                    "exchange",
                    "Request %s answered by %d datagram(s) in %.0f ms on attempt %d/%d "
                    "(%s -> %s; totals: %s; problems: %s)",
                    commands, len(replies), self.last_response_time * 1000, attempt,
                    retries, self.local_endpoint, self.remote_endpoint, self.traffic,
                    {k: v for k, v in self.stats.items() if v},
                )
                return replies

            if isinstance(self._protocol.error, ConnectionRefusedError):
                self.stats["refused"] += 1
                raise PanelRefusedError(
                    f"Panel at {self.host}:{self.port} refused the connection from "
                    f"local port {self.bound_port} (ICMP port unreachable): its network "
                    "module isn't accepting UDP on that port, e.g. while it restarts"
                )

            if self._protocol.error:
                self.stats["udp_errors"] += 1
                self.last_udp_error = str(self._protocol.error)
                last_error = PanelUDPError(f"UDP error: {self._protocol.error}")
                _THROTTLED.debug(
                    "udp_error", "UDP error for request %s (attempt %d/%d): %s",
                    commands, attempt, retries, self._protocol.error,
                )
            else:
                self.stats["timeouts"] += 1
                self.consecutive_timeouts += 1
                last_error = asyncio.TimeoutError()
                _THROTTLED.debug(
                    "timeout",
                    "No reply to request %s within %.1fs (attempt %d/%d, %d in a row)",
                    commands, timeout, attempt, retries, self.consecutive_timeouts,
                )
            if attempt < retries:
                await asyncio.sleep(0.3 * attempt)

        _THROTTLED.warning(
            "request_failed",
            "No usable reply to request %s from %s after %d attempts (local endpoint %s)",
            commands, self.remote_endpoint, retries, self.local_endpoint,
        )
        if isinstance(last_error, ConnectionError):
            raise last_error
        raise PanelNoResponseError(
            f"No response from panel at {self.host}:{self.port} "
            f"after {retries} attempts"
        )

    async def _collect_replies(
        self, expected: set[int] | None, settle_time: float, timeout: float
    ) -> tuple[list[bytes], float]:
        """Gather replies to the request just sent, until every block is in or time runs out.

        Once the first reply arrives, stragglers get at most ``settle_time`` to follow.
        Also returns the loop time the first reply was accepted (the deadline if none was).
        """
        assert self._protocol is not None
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        first_reply_at = deadline
        replies: list[bytes] = []
        seen: set[int] = set()
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                break
            try:
                await asyncio.wait_for(self._protocol.event.wait(), remaining)
            except asyncio.TimeoutError:
                break
            self._protocol.event.clear()
            if self._protocol.error is not None:
                break
            pending = self._protocol.responses[:]
            self._protocol.responses.clear()
            for datagram in pending:
                cmds = self._accept_reply(datagram, expected)
                if cmds is None:
                    continue
                if not replies:
                    first_reply_at = loop.time()
                    deadline = min(deadline, first_reply_at + settle_time)
                replies.append(datagram)
                seen |= cmds
            if replies and (expected is None or expected <= seen or CMD_ERROR in seen):
                break
        return replies, first_reply_at

    def _accept_reply(
        self, datagram: bytes, expected: set[int] | None
    ) -> set[int] | None:
        """Return the reply's command IDs, or None if it is corrupt or answers another request."""
        if crc_valid(datagram):
            self._crc_trusted = True
        elif self._crc_trusted:
            self.stats["corrupt_replies_dropped"] += 1
            # Length and header only: payloads may echo keypad entries.
            _THROTTLED.debug(
                "corrupt",
                "Dropping corrupt reply (bad length or CRC): %d bytes, header %s",
                len(datagram), datagram[:10].hex(),
            )
            return None
        cmds = set(packet_commands(datagram))
        if expected is not None and not cmds & (expected | {CMD_ERROR}):
            # Replies carry no request id; a late answer to an earlier request lands here.
            self.stats["stale_replies_dropped"] += 1
            _THROTTLED.debug(
                "stale",
                "Dropping reply for another request (commands %s, expected %s)",
                sorted(cmds), sorted(expected),
            )
            return None
        self.traffic["replies_received"] += 1
        self.consecutive_timeouts = 0
        self.last_reply_at = time.time()
        return cmds

    def _discard_unclaimed_replies(self) -> None:
        """Drop datagrams that arrived while no request was waiting for them, counting them."""
        assert self._protocol is not None
        if not self._protocol.responses:
            return
        count = len(self._protocol.responses)
        self.stats["stale_replies_dropped"] += count
        _THROTTLED.debug(
            "unclaimed",
            "Dropping %d reply datagram(s) that arrived after their request gave up "
            "(commands %s)",
            count, [packet_commands(d) for d in self._protocol.responses],
        )
        self._protocol.responses.clear()

    async def login(self, password: str) -> ParsedResponse:
        pkt = build_login_packet(password)
        responses = await self.send_receive(pkt)
        return parse_responses(responses)

    async def query(self, cmd: int, start: int, count: int) -> ParsedResponse:
        pkt = load_udl_pkt(cmd, start, count)
        responses = await self.send_receive(pkt)
        return parse_responses(responses)

    async def multi_query(
        self, queries: list[tuple[int, int, int]]
    ) -> ParsedResponse:
        if not queries:
            return ParsedResponse()
        cmd0, start0, count0 = queries[0]
        pkt = load_udl_pkt(cmd0, start0, count0)
        for cmd, start, count in queries[1:]:
            pkt = add_udl_pkt(pkt, cmd, start, count)
        responses = await self.send_receive(pkt)
        return parse_responses(responses)

    async def send_keypress(self, key_code: int, area_mask: int) -> ParsedResponse:
        pkt = build_keypress_packet(key_code, area_mask)
        # Commands aren't idempotent: a lost ack must not make us press the key twice.
        responses = await self.send_receive(
            pkt, retries=1, timeout=self.command_timeout
        )
        return parse_responses(responses)

    async def toggle_output(
        self, output_index: int, current_state: int
    ) -> ParsedResponse:
        pkt = build_output_toggle_packet(output_index, current_state)
        # Commands aren't idempotent: a lost ack must not make us press the key twice.
        responses = await self.send_receive(
            pkt, retries=1, timeout=self.command_timeout
        )
        return parse_responses(responses)

    async def send_data(
        self, cmd: int, start: int, count: int, data: bytes
    ) -> ParsedResponse:
        pkt = load_data_pkt(cmd, start, count, data)
        # Commands aren't idempotent: a lost ack must not make us press the key twice.
        responses = await self.send_receive(
            pkt, retries=1, timeout=self.command_timeout
        )
        return parse_responses(responses)

    async def send_keypad_char(self, char: str) -> ParsedResponse:
        pkt = build_keypad_char_packet(char)
        # Sent once like other commands; the ack's command ID isn't documented, so take any reply.
        responses = await self.send_receive(
            pkt, retries=1, match_commands=False, timeout=self.command_timeout
        )
        return parse_responses(responses)
