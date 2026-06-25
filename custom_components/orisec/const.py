"""Constants for the Orisec ControlPlus2 integration."""

from __future__ import annotations

DOMAIN = "orisec"
DEFAULT_PORT = 20202
POLL_INTERVAL = 2
UDP_TIMEOUT = 3.0
MAX_LOGIN_RETRIES = 3

CONF_PANEL_IP = "panel_ip"
CONF_PANEL_PORT = "panel_port"
CONF_PASSWORD = "password"

PLATFORMS = ["alarm_control_panel", "binary_sensor", "switch", "sensor"]

# ── Command IDs ──────────────────────────────────────────────────────────────

CMD_PASSWORD = 1
CMD_PANEL_INFO = 2
CMD_PANEL_STATE = 3
CMD_CONTROL_OUTPUT = 6
CMD_LCD = 9
CMD_KEYPAD_CHAR = 10
CMD_KEYPRESS = 11
CMD_EVENT_LOG = 12
CMD_SYS_CONFIG = 20
CMD_FOG = 23
CMD_ERROR = 99

# ── Status query command IDs ─────────────────────────────────────────────────

QUERY_ZONE_TYPES = 1110
QUERY_MAX_ZONES = 1114
QUERY_ZONE_TEXTS = 1120
QUERY_ZONE_WIRING = 1130
QUERY_ZONE_AREAS = 1140
QUERY_MAX_AREAS = 1141
QUERY_ZONE_BYPASS = 1150
QUERY_AREA_TEXTS = 2110
QUERY_AREA_ARM_MODE = 2120
QUERY_AREA_ARM_ATT = 2150
QUERY_MAX_REM_OUTPUTS = 3524
QUERY_PART_ARM_TEXTS = 3540
QUERY_REM_OUTPUT_TEXTS = 3520
QUERY_SYS_TEXT = 3510
QUERY_MAX_SYS_TEXT = 3514
QUERY_USER_TYPE = 8120
QUERY_UDL_OPTION = 7610
QUERY_ZONE_STATUS = 10110
QUERY_ZONE_TIMERS = 10120
QUERY_ZONE_STATUS2 = 10160
QUERY_SYS_OUTPUT_STATE = 10320
QUERY_REM_OUTPUT_STATE = 10340

# ── System output state array indices ────────────────────────────────────────

SOS_AC_FAULT = 1
SOS_ATS_FAULT = 2
SOS_SYS_OPEN = 3
SOS_JUST_DISARMED = 4
SOS_ARMED = 5
SOS_PART_ARMED = 6
SOS_ARMED_ALARM = 7
SOS_BELL = 8
SOS_STROBE = 9
SOS_ALARM = 10
SOS_CONFIRMED_ALARM = 11
SOS_CONFIRMED_PA = 12
SOS_ALARM_ABORT = 13
SOS_FIRE = 14
SOS_PA = 15
SOS_DURESS = 16
SOS_24HR = 17
SOS_MEDICAL = 18
SOS_TAMPER = 19
SOS_READY = 20
SOS_TROUBLE = 21
SOS_ALERT = 22
SOS_BYPASS = 23
SOS_BATTERY_FAULT = 31
SOS_IN_EXIT = 40
SOS_IN_ENTRY = 41
SOS_IN_2ND_ENTRY = 42
SOS_IN_ALARM = 43
SOS_CALL_ENGINEER = 48
SOS_PANEL_AC_ON = 57
SOS_ARMING_FAILED = 59
SOS_PART1 = 61
SOS_PART2 = 62
SOS_PART3 = 63

# ── Keypress codes ───────────────────────────────────────────────────────────

KEY_FULL_ARM = 0
KEY_PART1 = 1
KEY_PART2 = 2
KEY_PART3 = 3
KEY_DISARM = 4
KEY_RESET = 99
KEY_PA = 112

# ── Zone type definitions ────────────────────────────────────────────────────

ZONE_TYPE_NOT_USED = 0
ZONE_TYPE_FINAL_EXIT_1 = 1
ZONE_TYPE_FINAL_EXIT_2 = 2
ZONE_TYPE_ENTRY_ROUTE = 3
ZONE_TYPE_INTRUDER = 4
ZONE_TYPE_PERIMETER = 5
ZONE_TYPE_FIRE = 6
ZONE_TYPE_PA_SILENT = 7
ZONE_TYPE_PA_AUDIBLE = 8
ZONE_TYPE_PA_CONFIRMED = 9
ZONE_TYPE_PA_CONFIRMED_SILENT = 10
ZONE_TYPE_DISARMED_PA_SILENT = 11
ZONE_TYPE_DISARMED_PA_AUDIBLE = 12
ZONE_TYPE_MEDICAL = 13
ZONE_TYPE_24HR = 14
ZONE_TYPE_24HR_INT = 15
ZONE_TYPE_TAMPER = 16
ZONE_TYPE_EXIT_TERMINATOR = 17
ZONE_TYPE_FLOOD = 29
ZONE_TYPE_CO = 30
ZONE_TYPE_RTE_DOORBELL = 33

ZONE_TYPE_NAMES: dict[int, str] = {
    0: "Not Used",
    1: "Final Exit 1",
    2: "Final Exit 2",
    3: "Entry Route",
    4: "Intruder",
    5: "Perimeter",
    6: "Fire",
    7: "PA Silent",
    8: "PA Audible",
    9: "PA Confirmed",
    10: "PA Confirmed Silent",
    11: "Disarmed PA Silent",
    12: "Disarmed PA Audible",
    13: "Medical",
    14: "24 Hour",
    15: "24 Hour (Int)",
    16: "Tamper",
    17: "Exit Terminator",
    18: "Full Arm Key",
    19: "Part 1 Key",
    20: "Part 2 Key",
    21: "Part 3 Key",
    22: "Omit Key",
    23: "Security Key",
    24: "Auxiliary",
    25: "Warning",
    26: "Log/Monitor",
    27: "Fault",
    28: "Counter",
    29: "Flood 24 Hour",
    30: "CO 24 Hour",
    31: "Disarm Key",
    32: "Wireless Tamper",
    33: "RTE / Door Bell",
}

ZONE_TYPE_TO_DEVICE_CLASS: dict[int, str] = {
    1: "opening",
    2: "opening",
    3: "opening",
    4: "motion",
    5: "door",
    6: "smoke",
    7: "safety",
    8: "safety",
    9: "safety",
    10: "safety",
    11: "safety",
    12: "safety",
    13: "problem",
    14: "problem",
    15: "problem",
    16: "tamper",
    17: "opening",
    24: "problem",
    25: "problem",
    29: "moisture",
    30: "gas",
    33: "occupancy",
}

# ── Panel type lookup ────────────────────────────────────────────────────────

PANEL_TYPE_MAP: dict[int, str] = {
    40: "WCP40",
    110: "CP10",
    120: "CP20",
    140: "CP40",
    160: "EP100",
    200: "CP200",
}

# ── CRC16 table ──────────────────────────────────────────────────────────────

CRC16_INIT = 0xFFFF

CRC16_TABLE = [
    0x0000, 0x1021, 0x2042, 0x3063, 0x4084, 0x50A5, 0x60C6, 0x70E7,
    0x8108, 0x9129, 0xA14A, 0xB16B, 0xC18C, 0xD1AD, 0xE1CE, 0xF1EF,
    0x1231, 0x0210, 0x3273, 0x2252, 0x52B5, 0x4294, 0x72F7, 0x62D6,
    0x9339, 0x8318, 0xB37B, 0xA35A, 0xD3BD, 0xC39C, 0xF3FF, 0xE3DE,
    0x2462, 0x3443, 0x0420, 0x1401, 0x64E6, 0x74C7, 0x44A4, 0x5485,
    0xA56A, 0xB54B, 0x8528, 0x9509, 0xE5EE, 0xF5CF, 0xC5AC, 0xD58D,
    0x3653, 0x2672, 0x1611, 0x0630, 0x76D7, 0x66F6, 0x5695, 0x46B4,
    0xB75B, 0xA77A, 0x9719, 0x8738, 0xF7DF, 0xE7FE, 0xD79D, 0xC7BC,
    0x48C4, 0x58E5, 0x6886, 0x78A7, 0x0840, 0x1861, 0x2802, 0x3823,
    0xC9CC, 0xD9ED, 0xE98E, 0xF9AF, 0x8948, 0x9969, 0xA90A, 0xB92B,
    0x5AF5, 0x4AD4, 0x7AB7, 0x6A96, 0x1A71, 0x0A50, 0x3A33, 0x2A12,
    0xDBFD, 0xCBDC, 0xFBBF, 0xEB9E, 0x9B79, 0x8B58, 0xBB3B, 0xAB1A,
    0x6CA6, 0x7C87, 0x4CE4, 0x5CC5, 0x2C22, 0x3C03, 0x0C60, 0x1C41,
    0xEDAE, 0xFD8F, 0xCDEC, 0xDDCD, 0xAD2A, 0xBD0B, 0x8D68, 0x9D49,
    0x7E97, 0x6EB6, 0x5ED5, 0x4EF4, 0x3E13, 0x2E32, 0x1E51, 0x0E70,
    0xFF9F, 0xEFBE, 0xDFDD, 0xCFFC, 0xBF1B, 0xAF3A, 0x9F59, 0x8F78,
    0x9188, 0x81A9, 0xB1CA, 0xA1EB, 0xD10C, 0xC12D, 0xF14E, 0xE16F,
    0x1080, 0x00A1, 0x30C2, 0x20E3, 0x5004, 0x4025, 0x7046, 0x6067,
    0x83B9, 0x9398, 0xA3FB, 0xB3DA, 0xC33D, 0xD31C, 0xE37F, 0xF35E,
    0x02B1, 0x1290, 0x22F3, 0x32D2, 0x4235, 0x5214, 0x6277, 0x7256,
    0xB5EA, 0xA5CB, 0x95A8, 0x8589, 0xF56E, 0xE54F, 0xD52C, 0xC50D,
    0x34E2, 0x24C3, 0x14A0, 0x0481, 0x7466, 0x6447, 0x5424, 0x4405,
    0xA7DB, 0xB7FA, 0x8799, 0x97B8, 0xE75F, 0xF77E, 0xC71D, 0xD73C,
    0x26D3, 0x36F2, 0x0691, 0x16B0, 0x6657, 0x7676, 0x4615, 0x5634,
    0xD94C, 0xC96D, 0xF90E, 0xE92F, 0x99C8, 0x89E9, 0xB98A, 0xA9AB,
    0x5844, 0x4865, 0x7806, 0x6827, 0x18C0, 0x08E1, 0x3882, 0x28A3,
    0xCB7D, 0xDB5C, 0xEB3F, 0xFB1E, 0x8BF9, 0x9BD8, 0xABBB, 0xBB9A,
    0x4A75, 0x5A54, 0x6A37, 0x7A16, 0x0AF1, 0x1AD0, 0x2AB3, 0x3A92,
    0xFD2E, 0xED0F, 0xDD6C, 0xCD4D, 0xBDAA, 0xAD8B, 0x9DE8, 0x8DC9,
    0x7C26, 0x6C07, 0x5C64, 0x4C45, 0x3CA2, 0x2C83, 0x1CE0, 0x0CC1,
    0xEF1F, 0xFF3E, 0xCF5D, 0xDF7C, 0xAF9B, 0xBFBA, 0x8FD9, 0x9FF8,
    0x6E17, 0x7E36, 0x4E55, 0x5E74, 0x2E93, 0x3EB2, 0x0ED1, 0x1EF0,
]
