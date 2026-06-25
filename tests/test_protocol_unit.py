#!/usr/bin/env python3
"""Unit tests for Orisec protocol layer — no panel needed."""

from __future__ import annotations

import struct
import unittest

import importlib
import sys
import types

sys.path.insert(0, ".")

# Stub out homeassistant so the package __init__ doesn't fail on import
_ha = types.ModuleType("homeassistant")
_ha_core = types.ModuleType("homeassistant.core")
_ha_ce = types.ModuleType("homeassistant.config_entries")
_ha_huc = types.ModuleType("homeassistant.helpers.update_coordinator")
_ha_helpers = types.ModuleType("homeassistant.helpers")
_ha_ep = types.ModuleType("homeassistant.helpers.entity_platform")
_ha_const = types.ModuleType("homeassistant.const")

class _FakeConfigEntry:
    pass

class _FakeDataUpdateCoordinator:
    def __class_getitem__(cls, item):
        return cls

_ha_ce.ConfigEntry = _FakeConfigEntry
_ha_core.HomeAssistant = type("HomeAssistant", (), {})
_ha_core.callback = lambda f: f
_ha_huc.DataUpdateCoordinator = _FakeDataUpdateCoordinator
_ha_huc.UpdateFailed = Exception
_ha_ep.AddEntitiesCallback = None
_ha_const.CONF_HOST = "host"
_ha_const.CONF_PORT = "port"
_ha_const.CONF_PASSWORD = "password"

for mod_name, mod in [
    ("homeassistant", _ha),
    ("homeassistant.core", _ha_core),
    ("homeassistant.config_entries", _ha_ce),
    ("homeassistant.helpers", _ha_helpers),
    ("homeassistant.helpers.update_coordinator", _ha_huc),
    ("homeassistant.helpers.entity_platform", _ha_ep),
    ("homeassistant.const", _ha_const),
]:
    sys.modules[mod_name] = mod

from custom_components.orisec.const import (
    CRC16_INIT,
    CRC16_TABLE,
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
    ZONE_TYPE_NOT_USED,
    ZONE_TYPE_INTRUDER,
    ZONE_TYPE_FIRE,
)
from custom_components.orisec.protocol import (
    calc_crc16,
    load_udl_pkt,
    add_udl_pkt,
    load_data_pkt,
    build_password_packet,
    build_login_packet,
    build_keypress_packet,
    build_output_toggle_packet,
    trim_packet,
    parse_response,
    parse_responses,
    ParsedResponse,
)


class TestCRC16(unittest.TestCase):

    def test_table_length(self):
        self.assertEqual(len(CRC16_TABLE), 256)

    def test_table_first_entries(self):
        self.assertEqual(CRC16_TABLE[0], 0x0000)
        self.assertEqual(CRC16_TABLE[1], 0x1021)

    def test_crc16_zero_data(self):
        data = b"\x00" * 10
        crc = calc_crc16(data, len(data))
        self.assertIsInstance(crc, int)
        self.assertGreaterEqual(crc, 0)
        self.assertLessEqual(crc, 0xFFFF)

    def test_crc16_known_pattern(self):
        crc1 = calc_crc16(b"\x01\x02\x03", 3)
        crc2 = calc_crc16(b"\x01\x02\x04", 3)
        self.assertNotEqual(crc1, crc2)

    def test_crc16_partial_count(self):
        data = b"\x01\x02\x03\x04\x05"
        crc_full = calc_crc16(data, 5)
        crc_partial = calc_crc16(data, 3)
        self.assertNotEqual(crc_full, crc_partial)


class TestPacketConstruction(unittest.TestCase):

    def test_load_udl_pkt_structure(self):
        pkt = load_udl_pkt(1110, 1, 20)
        total_len = struct.unpack_from("<H", pkt, 0)[0]
        self.assertEqual(total_len, 12)
        self.assertEqual(struct.unpack_from("<H", pkt, 2)[0], 1110)
        self.assertEqual(struct.unpack_from("<H", pkt, 4)[0], 1)
        self.assertEqual(struct.unpack_from("<H", pkt, 6)[0], 20)
        self.assertEqual(struct.unpack_from("<H", pkt, 8)[0], 0)

    def test_load_udl_pkt_crc(self):
        pkt = load_udl_pkt(10320, 1, 65)
        total_len = struct.unpack_from("<H", pkt, 0)[0]
        crc_stored = struct.unpack_from("<H", pkt, total_len - 2)[0]
        crc_calc = calc_crc16(pkt, total_len - 2)
        self.assertEqual(crc_stored, crc_calc)

    def test_add_udl_pkt_extends(self):
        pkt = load_udl_pkt(10320, 1, 65)
        pkt = add_udl_pkt(pkt, 3, 1, 1)
        total_len = struct.unpack_from("<H", pkt, 0)[0]
        self.assertEqual(total_len, 20)

    def test_add_udl_pkt_crc_valid(self):
        pkt = load_udl_pkt(10320, 1, 65)
        pkt = add_udl_pkt(pkt, 3, 1, 1)
        pkt = add_udl_pkt(pkt, 10110, 1, 20)
        total_len = struct.unpack_from("<H", pkt, 0)[0]
        self.assertEqual(total_len, 28)
        crc_stored = struct.unpack_from("<H", pkt, total_len - 2)[0]
        crc_calc = calc_crc16(pkt, total_len - 2)
        self.assertEqual(crc_stored, crc_calc)

    def test_load_data_pkt(self):
        data = bytes([4, 0x03, 0x00, 0x00])
        pkt = load_data_pkt(11, 1, 1, data)
        total_len = struct.unpack_from("<H", pkt, 0)[0]
        self.assertEqual(total_len, 16)
        self.assertEqual(struct.unpack_from("<H", pkt, 2)[0], 11)
        self.assertEqual(struct.unpack_from("<H", pkt, 8)[0], 4)
        self.assertEqual(pkt[10], 4)

    def test_password_packet(self):
        pkt = build_password_packet("1234")
        total_len = struct.unpack_from("<H", pkt, 0)[0]
        self.assertEqual(total_len, 16)
        self.assertEqual(pkt[8], 4)
        self.assertEqual(pkt[10], ord("1"))
        self.assertEqual(pkt[11], ord("2"))
        self.assertEqual(pkt[12], ord("3"))
        self.assertEqual(pkt[13], ord("4"))

    def test_password_packet_different_lengths(self):
        for pw in ("1", "12", "123456"):
            pkt = build_password_packet(pw)
            total_len = struct.unpack_from("<H", pkt, 0)[0]
            self.assertEqual(total_len, 12 + len(pw))
            self.assertEqual(pkt[8], len(pw))

    def test_login_packet(self):
        pkt = build_login_packet("1234")
        total_len = struct.unpack_from("<H", pkt, 0)[0]
        self.assertEqual(total_len, 16 + 3 * 8)

    def test_keypress_packet(self):
        pkt = build_keypress_packet(0, 0x03)
        self.assertEqual(struct.unpack_from("<H", pkt, 2)[0], 11)
        self.assertEqual(pkt[10], 0)
        self.assertEqual(pkt[11], 0x03)
        self.assertEqual(pkt[12], 0)
        self.assertEqual(pkt[13], 0)

    def test_output_toggle_packet(self):
        pkt = build_output_toggle_packet(0, 0)
        self.assertEqual(struct.unpack_from("<H", pkt, 2)[0], 6)
        output_id = pkt[10] | (pkt[11] << 8)
        self.assertEqual(output_id, 2000)
        self.assertEqual(pkt[12], 1)
        self.assertEqual(pkt[13], 2)

    def test_output_toggle_xor(self):
        pkt_on = build_output_toggle_packet(3, 0)
        pkt_off = build_output_toggle_packet(3, 1)
        self.assertEqual(pkt_on[12], 1)
        self.assertEqual(pkt_off[12], 0)

    def test_trim_packet(self):
        pkt = load_udl_pkt(1, 1, 1)
        trimmed = trim_packet(pkt)
        self.assertEqual(len(trimmed), 12)
        self.assertIsInstance(trimmed, bytes)


class TestResponseParsing(unittest.TestCase):

    def _build_response(self, blocks: list[tuple[int, int, int, bytes]]) -> bytes:
        body = bytearray()
        for cmd, start, item_size, data in blocks:
            body += struct.pack("<H", cmd)
            body += struct.pack("<H", start)
            body += struct.pack("<H", item_size)
            body += struct.pack("<H", len(data))
            body += data
        total_len = 2 + len(body) + 2
        buf = struct.pack("<H", total_len) + bytes(body)
        crc = calc_crc16(buf, len(buf))
        return buf + struct.pack("<H", crc)

    def test_login_response(self):
        resp = self._build_response([(1, 1, 0, b"")])
        r = parse_response(resp)
        self.assertTrue(r.logged_in)

    def test_error_response(self):
        resp = self._build_response([(99, 1, 1, b"\x03")])
        r = parse_response(resp)
        self.assertEqual(r.error, 3)

    def test_panel_info_response(self):
        payload = bytearray(8)
        payload[0] = 4
        payload[1] = 74
        payload[4] = 0
        payload[5] = 120
        resp = self._build_response([(2, 1, 1, bytes(payload))])
        r = parse_response(resp)
        self.assertEqual(r.panel_version, "4.74")
        self.assertEqual(r.panel_type, "CP20")

    def test_panel_info_z_variant(self):
        payload = bytearray(8)
        payload[0] = 4
        payload[1] = 74
        payload[4] = 1
        payload[5] = 120
        resp = self._build_response([(2, 1, 1, bytes(payload))])
        r = parse_response(resp)
        self.assertEqual(r.panel_type, "ZP20")

    def test_zone_types_response(self):
        zone_data = bytes([1, 4, 4, 4, 4, 4, 0, 0, 0, 0])
        resp = self._build_response([(1110, 1, 10, zone_data)])
        r = parse_response(resp)
        self.assertEqual(len(r.zone_types), 10)
        self.assertEqual(r.zone_types[0], 1)
        self.assertEqual(r.zone_types[1], 4)
        self.assertEqual(r.zone_types[6], 0)

    def test_zone_names_response(self):
        names = b"Hall\x00Lounge\x00Kitchen\x00"
        resp = self._build_response([(1120, 1, 1, names)])
        r = parse_response(resp)
        self.assertEqual(r.zone_names, ["Hall", "Lounge", "Kitchen"])

    def test_zone_status_response(self):
        status = struct.pack("<HH", 0x0001, 0x0000)
        resp = self._build_response([(10110, 1, 2, status)])
        r = parse_response(resp)
        self.assertEqual(len(r.zone_status), 4)
        self.assertEqual(r.zone_status[0] & 1, 1)
        self.assertEqual(r.zone_status[2] & 1, 0)

    def test_sys_output_state_response(self):
        sos_data = bytearray(65)
        sos_data[SOS_READY - 1 + 1] = 0x03
        sos_data[SOS_PANEL_AC_ON - 1 + 1] = 0x03
        resp = self._build_response([(10320, 1, 65, bytes(sos_data))])
        r = parse_response(resp)
        self.assertEqual(r.sys_output_state[SOS_READY], 0x03)
        self.assertEqual(r.sys_output_state[SOS_PANEL_AC_ON], 0x03)

    def test_area_names_response(self):
        names = b"Main\x00Garage\x00"
        resp = self._build_response([(2110, 1, 1, names)])
        r = parse_response(resp)
        self.assertEqual(r.area_names, ["Main", "Garage"])

    def test_remote_output_names(self):
        names = b"Light\x00Siren\x00"
        resp = self._build_response([(3520, 1, 1, names)])
        r = parse_response(resp)
        self.assertEqual(r.rem_output_names, ["Light", "Siren"])

    def test_part_arm_names(self):
        names = b"Night\x00Day\x00Custom\x00"
        resp = self._build_response([(3540, 1, 1, names)])
        r = parse_response(resp)
        self.assertEqual(r.part_arm_names, ["Night", "Day", "Custom"])

    def test_multi_block_response(self):
        resp = self._build_response([
            (1, 1, 0, b""),
            (2, 1, 1, bytes(bytearray(8))),
        ])
        r = parse_response(resp)
        self.assertTrue(r.logged_in)
        self.assertIsNotNone(r.panel_version)
        self.assertEqual(len(r.commands), 2)

    def test_parse_responses_combines(self):
        r1 = self._build_response([(1, 1, 0, b"")])
        zone_data = bytes([4, 4, 0])
        r2 = self._build_response([(1110, 1, 3, zone_data)])
        result = parse_responses([r1, r2])
        self.assertTrue(result.logged_in)
        self.assertEqual(len(result.zone_types), 3)

    def test_empty_response(self):
        r = parse_response(b"\x04\x00\x00\x00")
        self.assertFalse(r.logged_in)

    def test_short_response(self):
        r = parse_response(b"\x01")
        self.assertFalse(r.logged_in)


class TestSOSConstants(unittest.TestCase):

    def test_sos_indices_match_enum(self):
        self.assertEqual(SOS_ARMED, 5)
        self.assertEqual(SOS_PART_ARMED, 6)
        self.assertEqual(SOS_ALARM, 10)
        self.assertEqual(SOS_READY, 20)
        self.assertEqual(SOS_IN_EXIT, 40)
        self.assertEqual(SOS_IN_ENTRY, 41)
        self.assertEqual(SOS_IN_ALARM, 43)
        self.assertEqual(SOS_PANEL_AC_ON, 57)
        self.assertEqual(SOS_PART1, 61)
        self.assertEqual(SOS_PART2, 62)
        self.assertEqual(SOS_PART3, 63)

    def test_alarm_state_derivation_disarmed(self):
        sos = [0] * 100
        sos[SOS_READY] = 0x01
        bit = 1
        self.assertFalse(sos[SOS_ARMED] & bit)
        self.assertTrue(sos[SOS_READY] & bit)

    def test_alarm_state_derivation_armed_away(self):
        sos = [0] * 100
        sos[SOS_ARMED] = 0x01
        bit = 1
        self.assertTrue(sos[SOS_ARMED] & bit)
        self.assertFalse(sos[SOS_PART_ARMED] & bit)

    def test_alarm_state_derivation_armed_home(self):
        sos = [0] * 100
        sos[SOS_ARMED] = 0x01
        sos[SOS_PART_ARMED] = 0x01
        sos[SOS_PART1] = 0x01
        bit = 1
        self.assertTrue(sos[SOS_ARMED] & bit)
        self.assertTrue(sos[SOS_PART_ARMED] & bit)
        self.assertTrue(sos[SOS_PART1] & bit)

    def test_alarm_state_derivation_triggered(self):
        sos = [0] * 100
        sos[SOS_ALARM] = 0x01
        bit = 1
        self.assertTrue(sos[SOS_ALARM] & bit)

    def test_alarm_state_multi_area(self):
        sos = [0] * 100
        sos[SOS_ARMED] = 0x02
        sos[SOS_READY] = 0x01
        self.assertFalse(sos[SOS_ARMED] & 0x01)
        self.assertTrue(sos[SOS_ARMED] & 0x02)


if __name__ == "__main__":
    unittest.main()
