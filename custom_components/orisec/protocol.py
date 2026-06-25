"""Async UDP protocol for Orisec ControlPlus2 panels."""

from __future__ import annotations

import asyncio
import logging
import struct
from dataclasses import dataclass, field
from typing import Any

from .const import (
    CMD_CONTROL_OUTPUT,
    CMD_ERROR,
    CMD_KEYPRESS,
    CMD_PANEL_INFO,
    CMD_PANEL_STATE,
    CMD_PASSWORD,
    CMD_SYS_CONFIG,
    CRC16_INIT,
    CRC16_TABLE,
    PANEL_TYPE_MAP,
    QUERY_AREA_ARM_ATT,
    QUERY_AREA_ARM_MODE,
    QUERY_AREA_TEXTS,
    QUERY_MAX_AREAS,
    QUERY_MAX_REM_OUTPUTS,
    QUERY_MAX_ZONES,
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
    UDP_TIMEOUT,
)

_LOGGER = logging.getLogger(__name__)


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


def trim_packet(buf: bytearray) -> bytes:
    total_len = struct.unpack_from("<H", buf, 0)[0]
    return bytes(buf[:total_len])


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
    commands: list[dict[str, Any]] = field(default_factory=list)


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


class OrisecUDPProtocol(asyncio.DatagramProtocol):

    def __init__(self) -> None:
        self.responses: list[bytes] = []
        self.event = asyncio.Event()
        self.transport: asyncio.DatagramTransport | None = None
        self.error: Exception | None = None

    def connection_made(self, transport: asyncio.DatagramTransport) -> None:  # type: ignore[override]
        self.transport = transport

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:  # type: ignore[override]
        self.responses.append(data)
        self.event.set()

    def error_received(self, exc: Exception) -> None:
        _LOGGER.debug("UDP error: %s", exc)
        self.error = exc

    def connection_lost(self, exc: Exception | None) -> None:
        pass


class OrisecConnection:

    def __init__(self, host: str, port: int, timeout: float = UDP_TIMEOUT) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self._transport: asyncio.DatagramTransport | None = None
        self._protocol: OrisecUDPProtocol | None = None

    async def connect(self) -> None:
        if self._transport is not None:
            return
        loop = asyncio.get_running_loop()
        self._transport, self._protocol = await loop.create_datagram_endpoint(
            OrisecUDPProtocol,
            remote_addr=(self.host, self.port),
        )

    async def disconnect(self) -> None:
        if self._transport is not None:
            self._transport.close()
            self._transport = None
            self._protocol = None

    @property
    def connected(self) -> bool:
        return self._transport is not None and not self._transport.is_closing()

    async def send_receive(
        self, packet: bytearray | bytes, settle_time: float = 0.2
    ) -> list[bytes]:
        if self._transport is None or self._protocol is None:
            raise ConnectionError("Not connected")

        data = trim_packet(bytearray(packet)) if isinstance(packet, bytes) else trim_packet(packet)

        self._protocol.responses.clear()
        self._protocol.event.clear()
        self._protocol.error = None

        self._transport.sendto(data)

        try:
            await asyncio.wait_for(self._protocol.event.wait(), self.timeout)
            await asyncio.sleep(settle_time)
        except asyncio.TimeoutError:
            _LOGGER.debug("UDP timeout waiting for response")
            return []

        if self._protocol.error:
            raise ConnectionError(f"UDP error: {self._protocol.error}")

        return self._protocol.responses[:]

    async def login(self, password: str) -> ParsedResponse:
        pkt = build_login_packet(password)
        responses = await self.send_receive(pkt)
        if not responses:
            raise ConnectionError("No response from panel during login")
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
        responses = await self.send_receive(pkt)
        return parse_responses(responses)

    async def toggle_output(
        self, output_index: int, current_state: int
    ) -> ParsedResponse:
        pkt = build_output_toggle_packet(output_index, current_state)
        responses = await self.send_receive(pkt)
        return parse_responses(responses)

    async def send_data(
        self, cmd: int, start: int, count: int, data: bytes
    ) -> ParsedResponse:
        pkt = load_data_pkt(cmd, start, count, data)
        responses = await self.send_receive(pkt)
        return parse_responses(responses)
