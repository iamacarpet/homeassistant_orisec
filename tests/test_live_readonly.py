#!/usr/bin/env python3
"""Read-only test suite for Orisec ControlPlus2 panel communication.

This script performs a comprehensive series of read-only queries against
a live Orisec panel over local UDP. It does NOT arm, disarm, toggle outputs,
or modify any panel state — it only reads data.

Usage:
    python -m tests.test_live_readonly --host 192.168.1.100 --password YOUR_PIN

Exit codes:
    0 = all tests passed
    1 = one or more tests failed
    2 = could not connect / login
"""

from __future__ import annotations

import argparse
import asyncio
import struct
import sys
import time
from dataclasses import dataclass

sys.path.insert(0, ".")

from custom_components.orisec.const import (
    CRC16_TABLE,
    CRC16_INIT,
    ZONE_TYPE_NAMES,
    ZONE_TYPE_TO_DEVICE_CLASS,
    PANEL_TYPE_MAP,
    SOS_ARMED,
    SOS_PART_ARMED,
    SOS_ALARM,
    SOS_READY,
    SOS_IN_EXIT,
    SOS_IN_ENTRY,
    SOS_IN_ALARM,
    SOS_PANEL_AC_ON,
    SOS_PART1,
    SOS_PART2,
    SOS_PART3,
    SOS_TROUBLE,
    SOS_BYPASS,
    SOS_BELL,
    SOS_FIRE,
    SOS_PA,
    SOS_SYS_OPEN,
    SOS_JUST_DISARMED,
    SOS_CALL_ENGINEER,
    SOS_AC_FAULT,
    SOS_BATTERY_FAULT,
)
from custom_components.orisec.protocol import (
    OrisecConnection,
    ParsedResponse,
    calc_crc16,
    load_udl_pkt,
    add_udl_pkt,
    trim_packet,
    build_password_packet,
    build_login_packet,
    parse_response,
    parse_responses,
)


@dataclass
class TestResult:
    name: str
    passed: bool
    message: str
    duration: float = 0.0


class LiveTestSuite:

    def __init__(self, host: str, port: int, password: str, verbose: bool = False):
        self.host = host
        self.port = port
        self.password = password
        self.verbose = verbose
        self.conn = OrisecConnection(host, port)
        self.results: list[TestResult] = []
        self.login_result: ParsedResponse | None = None

    def log(self, msg: str) -> None:
        if self.verbose:
            print(f"  {msg}")

    async def run_all(self) -> bool:
        print(f"Orisec ControlPlus2 Read-Only Test Suite")
        print(f"Target: {self.host}:{self.port}")
        print(f"{'=' * 60}\n")

        try:
            await self.conn.connect()
        except (OSError, ConnectionError) as e:
            print(f"FATAL: Cannot connect to {self.host}:{self.port}: {e}")
            return False

        try:
            await self.test_crc16_computation()
            await self.test_packet_construction()
            await self.test_login()

            if not self.login_result or not self.login_result.logged_in:
                print("\nFATAL: Login failed, cannot run remaining tests")
                self.print_summary()
                return False

            await asyncio.sleep(0.3)
            await self.test_panel_info()
            await asyncio.sleep(0.3)
            await self.test_system_config()
            await asyncio.sleep(0.3)
            await self.test_system_output_states()
            await asyncio.sleep(0.3)
            await self.test_zone_types()
            await asyncio.sleep(0.3)
            await self.test_zone_names()
            await asyncio.sleep(0.3)
            await self.test_zone_status()
            await asyncio.sleep(0.3)
            await self.test_zone_areas()
            await asyncio.sleep(0.3)
            await self.test_area_names()
            await asyncio.sleep(0.3)
            await self.test_remote_output_names()
            await asyncio.sleep(0.3)
            await self.test_remote_output_states()
            await asyncio.sleep(0.3)
            await self.test_part_arm_texts()
            await asyncio.sleep(0.3)
            await self.test_alarm_state_derivation()
            await asyncio.sleep(0.3)
            await self.test_zone_timers()
            await asyncio.sleep(0.3)
            await self.test_multi_query()
        finally:
            await self.conn.disconnect()

        self.print_summary()
        return all(r.passed for r in self.results)

    def add_result(self, name: str, passed: bool, message: str, duration: float = 0.0):
        self.results.append(TestResult(name, passed, message, duration))
        status = "PASS" if passed else "FAIL"
        time_str = f" ({duration:.3f}s)" if duration > 0 else ""
        print(f"  [{status}] {name}{time_str}")
        if not passed or self.verbose:
            print(f"         {message}")

    async def test_crc16_computation(self) -> None:
        print("\n--- CRC16 Computation ---")
        test_data = b"\x0c\x00\x01\x00\x01\x00\x01\x00\x04\x00"
        crc = calc_crc16(test_data, len(test_data))
        self.add_result(
            "CRC16 basic",
            crc != 0 and isinstance(crc, int),
            f"CRC16({test_data.hex()}) = 0x{crc:04x}",
        )

        pkt = load_udl_pkt(1, 1, 1)
        total_len = struct.unpack_from("<H", pkt, 0)[0]
        crc_stored = struct.unpack_from("<H", pkt, total_len - 2)[0]
        crc_calc = calc_crc16(pkt, total_len - 2)
        self.add_result(
            "CRC16 packet verify",
            crc_stored == crc_calc,
            f"stored=0x{crc_stored:04x} calc=0x{crc_calc:04x}",
        )

    async def test_packet_construction(self) -> None:
        print("\n--- Packet Construction ---")
        pkt = load_udl_pkt(1110, 1, 20)
        total_len = struct.unpack_from("<H", pkt, 0)[0]
        cmd = struct.unpack_from("<H", pkt, 2)[0]
        start = struct.unpack_from("<H", pkt, 4)[0]
        count = struct.unpack_from("<H", pkt, 6)[0]

        self.add_result(
            "LoadUdlPkt format",
            total_len == 12 and cmd == 1110 and start == 1 and count == 20,
            f"len={total_len} cmd={cmd} start={start} count={count}",
        )

        pkt = load_udl_pkt(10320, 1, 65)
        pkt = add_udl_pkt(pkt, 3, 1, 1)
        total_len = struct.unpack_from("<H", pkt, 0)[0]
        self.add_result(
            "AddUdlPkt multi-cmd",
            total_len == 20,
            f"combined len={total_len} (expected 20)",
        )

        pw_pkt = build_password_packet("1234")
        total_len = struct.unpack_from("<H", pw_pkt, 0)[0]
        data_len = pw_pkt[8]
        self.add_result(
            "Password packet",
            total_len == 16 and data_len == 4,
            f"len={total_len} datalen={data_len}",
        )

    async def test_login(self) -> None:
        print("\n--- Login ---")
        t0 = time.monotonic()
        try:
            self.login_result = await self.conn.login(self.password)
            dur = time.monotonic() - t0

            if self.login_result.logged_in:
                self.add_result("Login", True, "Access granted", dur)
            elif self.login_result.error == 3:
                self.add_result("Login", False, "Password rejected", dur)
            else:
                self.add_result(
                    "Login", False,
                    f"Error code: {self.login_result.error}", dur,
                )
        except Exception as e:
            dur = time.monotonic() - t0
            self.add_result("Login", False, f"Exception: {e}", dur)

    async def test_panel_info(self) -> None:
        print("\n--- Panel Info ---")
        r = self.login_result
        if not r:
            self.add_result("Panel info", False, "No login result")
            return

        self.add_result(
            "Panel type",
            r.panel_type is not None and len(r.panel_type) > 0,
            f"type={r.panel_type} (id={r.panel_id}, var={r.panel_var})",
        )
        self.add_result(
            "Panel version",
            r.panel_version is not None,
            f"version={r.panel_version}",
        )

    async def test_system_config(self) -> None:
        print("\n--- System Config ---")
        r = self.login_result
        if not r:
            self.add_result("System config", False, "No login result")
            return

        self.add_result(
            "Serial number",
            r.serial is not None and len(r.serial or "") > 0,
            f"serial={r.serial}",
        )
        self.add_result(
            "Max zones",
            r.max_zones > 0,
            f"max_zones={r.max_zones}",
        )
        self.add_result(
            "Max areas",
            r.max_areas > 0,
            f"max_areas={r.max_areas}",
        )
        self.add_result(
            "Max remote outputs",
            r.max_rem_outputs >= 0,
            f"max_rem_outputs={r.max_rem_outputs}",
        )
        self.add_result(
            "Part arm mask",
            r.part_arm_mask >= 0,
            f"part_arm_mask={r.part_arm_mask:03b}",
        )
        self.add_result(
            "User area",
            r.user_area > 0,
            f"user_area=0x{r.user_area:x} (user_number={r.user_number})",
        )

    async def test_system_output_states(self) -> None:
        print("\n--- System Output States ---")
        t0 = time.monotonic()
        r = await self.conn.query(10320, 1, 65)
        dur = time.monotonic() - t0

        sos = r.sys_output_state
        has_data = any(sos[i] != 0 for i in range(65))
        self.add_result(
            "SOS query",
            has_data,
            f"65 bytes received, non-zero entries found" if has_data else "All zeros",
            dur,
        )

        ac_on = bool(sos[SOS_PANEL_AC_ON] & 0xFF)
        self.add_result(
            "AC power detection",
            True,
            f"Panel AC: {'ON' if ac_on else 'OFF'} (index {SOS_PANEL_AC_ON}=0x{sos[SOS_PANEL_AC_ON]:02x})",
        )

        self.log(f"Non-zero SOS entries:")
        for i in range(65):
            if sos[i] != 0:
                self.log(f"  [{i:2d}] = 0x{sos[i]:04x} ({sos[i]:016b})")

    async def test_zone_types(self) -> None:
        print("\n--- Zone Types ---")
        max_zones = self.login_result.max_zones if self.login_result else 20
        t0 = time.monotonic()
        r = await self.conn.query(1110, 1, max_zones)
        dur = time.monotonic() - t0

        zt = r.zone_types
        self.add_result(
            "Zone types query",
            len(zt) > 0,
            f"{len(zt)} bytes received for {max_zones} zones",
            dur,
        )

        used = sum(1 for i in range(min(len(zt), max_zones)) if zt[i] != 0)
        self.add_result(
            "Zone types parse",
            True,
            f"{used} used zones out of {max_zones}",
        )

        for i in range(min(len(zt), max_zones)):
            if zt[i] != 0:
                zt_name = ZONE_TYPE_NAMES.get(zt[i], f"Type{zt[i]}")
                dc = ZONE_TYPE_TO_DEVICE_CLASS.get(zt[i], "none")
                self.log(f"  Zone {i + 1}: {zt_name} -> device_class={dc}")

    async def test_zone_names(self) -> None:
        print("\n--- Zone Names ---")
        max_zones = self.login_result.max_zones if self.login_result else 20
        batch = min(max_zones, 15)
        t0 = time.monotonic()
        r = await self.conn.query(1120, 1, batch)
        dur = time.monotonic() - t0

        names = r.zone_names
        self.add_result(
            "Zone names query",
            len(names) > 0,
            f"{len(names)} zone names received (batch of {batch})",
            dur,
        )

        named = [n for n in names if n]
        self.add_result(
            "Named zones",
            True,
            f"{len(named)} zones have names",
        )
        for i, name in enumerate(names):
            if name:
                self.log(f"  Zone {i + 1}: '{name}'")

        if max_zones > 15:
            await asyncio.sleep(0.3)
            r2 = await self.conn.query(1120, 16, max_zones - 15)
            more = [n for n in r2.zone_names if n]
            self.add_result(
                "Zone names batch 2",
                True,
                f"{len(more)} additional named zones (zones 16+)",
            )

    async def test_zone_status(self) -> None:
        print("\n--- Zone Status ---")
        max_zones = self.login_result.max_zones if self.login_result else 20
        t0 = time.monotonic()
        r = await self.conn.query(10110, 1, max_zones)
        dur = time.monotonic() - t0

        zs = r.zone_status
        self.add_result(
            "Zone status query",
            len(zs) > 0,
            f"{len(zs)} bytes received (item_size={r.zone_status_item_size})",
            dur,
        )

        for i in range(max_zones):
            byte_idx = i * 2
            if byte_idx + 1 < len(zs):
                val = zs[byte_idx] | (zs[byte_idx + 1] << 8)
                if val != 0:
                    active = "OPEN" if val & 1 else "closed"
                    tamper = " TAMPER" if val & 2 else ""
                    self.log(f"  Zone {i + 1}: 0x{val:04x} ({active}{tamper})")

    async def test_zone_areas(self) -> None:
        print("\n--- Zone Area Assignment ---")
        max_zones = self.login_result.max_zones if self.login_result else 20
        t0 = time.monotonic()
        r = await self.conn.query(1140, 1, min(max_zones, 100))
        dur = time.monotonic() - t0

        za = r.zone_areas
        self.add_result(
            "Zone areas query",
            len(za) > 0,
            f"{len(za)} bytes received",
            dur,
        )

        for i in range(min(len(za), max_zones)):
            if za[i] != 0:
                self.log(f"  Zone {i + 1}: area_mask=0x{za[i]:02x} ({za[i]:08b})")

    async def test_area_names(self) -> None:
        print("\n--- Area Names ---")
        max_areas = self.login_result.max_areas if self.login_result else 2
        t0 = time.monotonic()
        r = await self.conn.query(2110, 1, max_areas)
        dur = time.monotonic() - t0

        names = r.area_names
        self.add_result(
            "Area names query",
            len(names) > 0,
            f"{len(names)} area names received",
            dur,
        )

        for i, name in enumerate(names):
            if name:
                self.log(f"  Area {i + 1}: '{name}'")

    async def test_remote_output_names(self) -> None:
        print("\n--- Remote Output Names ---")
        max_rem = (
            self.login_result.max_rem_outputs if self.login_result else 0
        )
        if max_rem == 0:
            self.add_result("Remote output names", True, "No remote outputs configured")
            return

        t0 = time.monotonic()
        r = await self.conn.query(3520, 1, max_rem)
        dur = time.monotonic() - t0

        names = r.rem_output_names
        self.add_result(
            "Remote output names query",
            True,
            f"{len(names)} output names received",
            dur,
        )
        for i, name in enumerate(names):
            if name:
                self.log(f"  Output {i + 1}: '{name}'")

    async def test_remote_output_states(self) -> None:
        print("\n--- Remote Output States ---")
        max_rem = (
            self.login_result.max_rem_outputs if self.login_result else 0
        )
        if max_rem == 0:
            self.add_result("Remote output states", True, "No remote outputs")
            return

        t0 = time.monotonic()
        r = await self.conn.query(10340, 1, max_rem + 1)
        dur = time.monotonic() - t0

        ros = r.rem_output_state
        self.add_result(
            "Remote output states query",
            len(ros) > 0,
            f"{len(ros)} bytes received",
            dur,
        )
        for i in range(max_rem):
            val = ros[i] if i < len(ros) else 0
            self.log(f"  Output {i + 1}: {'ON' if val else 'OFF'} (raw={val})")

    async def test_part_arm_texts(self) -> None:
        print("\n--- Part Arm Texts ---")
        t0 = time.monotonic()
        r = await self.conn.query(3540, 1, 3)
        dur = time.monotonic() - t0

        names = r.part_arm_names
        self.add_result(
            "Part arm texts query",
            True,
            f"{len(names)} part arm names received",
            dur,
        )
        for i, name in enumerate(names):
            if name:
                self.log(f"  Part Arm {i + 1}: '{name}'")

    async def test_alarm_state_derivation(self) -> None:
        print("\n--- Alarm State Derivation ---")
        r = await self.conn.query(10320, 1, 65)
        sos = r.sys_output_state
        max_areas = self.login_result.max_areas if self.login_result else 2

        for area_idx in range(max_areas):
            bit = 1 << area_idx

            if sos[SOS_ALARM] & bit or sos[SOS_IN_ALARM] & bit:
                state = "triggered"
            elif sos[SOS_ARMED] & bit:
                if sos[SOS_PART_ARMED] & bit:
                    state = "armed_home"
                    if sos[SOS_PART1] & bit:
                        state += " (Part 1)"
                    elif sos[SOS_PART2] & bit:
                        state += " (Part 2)"
                    elif sos[SOS_PART3] & bit:
                        state += " (Part 3)"
                else:
                    state = "armed_away"
            elif sos[SOS_IN_EXIT] & bit:
                state = "arming"
            elif sos[SOS_IN_ENTRY] & bit:
                state = "pending"
            else:
                state = "disarmed"

            ready = "ready" if sos[SOS_READY] & bit else "not ready"

            area_name = f"Area {area_idx + 1}"
            self.add_result(
                f"Area {area_idx + 1} state",
                True,
                f"{area_name}: {state} ({ready})",
            )

    async def test_zone_timers(self) -> None:
        print("\n--- Zone Timers ---")
        max_zones = self.login_result.max_zones if self.login_result else 20
        t0 = time.monotonic()
        r = await self.conn.query(10120, 1, max_zones)
        dur = time.monotonic() - t0

        zt = r.zone_timers
        self.add_result(
            "Zone timers query",
            len(zt) > 0,
            f"{len(zt)} bytes received",
            dur,
        )

        for i in range(max_zones):
            byte_idx = i * 2
            if byte_idx + 1 < len(zt):
                val = zt[byte_idx] | (zt[byte_idx + 1] << 8)
                if val > 0:
                    self.log(f"  Zone {i + 1}: timer={val}s")

    async def test_multi_query(self) -> None:
        print("\n--- Multi-Query Packet ---")
        max_zones = self.login_result.max_zones if self.login_result else 20

        t0 = time.monotonic()
        r = await self.conn.multi_query([
            (10320, 1, 65),
            (3, 1, 1),
            (10110, 1, max_zones),
        ])
        dur = time.monotonic() - t0

        has_sos = any(r.sys_output_state[i] != 0 for i in range(65))
        has_zs = len(r.zone_status) > 0

        self.add_result(
            "Multi-query",
            has_sos and has_zs,
            f"SOS={has_sos}, zone_status={has_zs}, commands={len(r.commands)}",
            dur,
        )

    def print_summary(self) -> None:
        print(f"\n{'=' * 60}")
        passed = sum(1 for r in self.results if r.passed)
        failed = sum(1 for r in self.results if not r.passed)
        total = len(self.results)
        total_time = sum(r.duration for r in self.results)

        print(f"Results: {passed}/{total} passed, {failed} failed ({total_time:.2f}s)")

        if failed > 0:
            print(f"\nFailed tests:")
            for r in self.results:
                if not r.passed:
                    print(f"  - {r.name}: {r.message}")

        if self.login_result and self.login_result.logged_in:
            print(f"\nPanel Summary:")
            print(f"  Type: {self.login_result.panel_type} v{self.login_result.panel_version}")
            print(f"  Zones: {self.login_result.max_zones}")
            print(f"  Areas: {self.login_result.max_areas}")
            print(f"  Remote outputs: {self.login_result.max_rem_outputs}")
            print(f"  Part arm mask: {self.login_result.part_arm_mask:03b}")


async def main():
    parser = argparse.ArgumentParser(
        description="Orisec ControlPlus2 Read-Only Test Suite"
    )
    parser.add_argument("--host", required=True, help="Panel IP address")
    parser.add_argument("--port", type=int, default=20202, help="Panel port (default: 20202)")
    parser.add_argument("--password", required=True, help="Panel password/PIN")
    parser.add_argument("-v", "--verbose", action="store_true", help="Show detailed output")
    args = parser.parse_args()

    suite = LiveTestSuite(args.host, args.port, args.password, args.verbose)
    success = await suite.run_all()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())
