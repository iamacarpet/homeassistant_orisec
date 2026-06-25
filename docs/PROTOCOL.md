# Orisec ControlPlus2 Protocol Reference

This document describes the binary UDP protocol used by the Orisec ControlPlus2 family of alarm panels (CP10, CP20, CP40, CP200, EP100, and Z-variants).

## Transport

The protocol operates over UDP with two transport modes:

### Local LAN (Direct)

- **Port:** 20202
- **Encryption:** None — raw binary packets
- **Addressing:** Direct to panel IP on the local network
- **Latency:** Typically < 10ms
- **Push notifications:** Not available; clients must poll

This is the preferred mode for home automation integrations. The panel listens for UDP datagrams on port 20202 and responds to the same source address.

### Cloud Relay

- **Port:** 15000
- **Servers:** Round-robin across multiple relay hosts:
  - `UKDC1.fireandsecurityapps.co.uk`
  - `UKDC2.fireandsecurityapps.co.uk`
  - `orisec.hopto.org`
  - `orisec2.hopto.org`
- **Encryption:** XOR-based stream cipher (see [Cloud Relay Protocol](#cloud-relay-protocol))
- **Authentication:** Requires serial number + authorisation key

The cloud relay acts as a NAT traversal service: the mobile app sends UDP packets to the relay server, which forwards them to the panel (which maintains a persistent connection to the server).

---

## Packet Format

### Request Packet (LoadUdlPkt)

All request packets follow a fixed structure:

```
Offset  Size  Field
──────  ────  ─────────────────────
0       2     Total packet length (LE uint16)
2       2     Command ID (LE uint16)
4       2     Start index (LE uint16)
6       2     Count (LE uint16)
8       2     Data length (LE uint16, 0 for queries)
10      N     Data payload (if data_length > 0)
N+10    2     CRC16 checksum (LE uint16)
```

All multi-byte fields are **little-endian**.

**Minimum packet:** 12 bytes (no data payload — the `data_length` field at offset 8 is 0, and the CRC occupies bytes 10–11).

### Multi-Command Packets (AddUdlPkt)

Multiple commands can be chained into a single packet. The `AddUdlPkt` function appends another command header (8 bytes) before the CRC:

```
[total_len] [cmd1 header] [cmd1 data?] [cmd2 header] [cmd2 data?] ... [CRC16]
```

The total length field at offset 0 is updated to reflect the full packet size. The CRC at the end covers all bytes from offset 0 to `total_len - 2`.

### Data Packets (LoadDataPkt)

When sending data (e.g., keypress commands, output toggles):

```
Offset  Size  Field
──────  ────  ─────────────────────
0       2     Total length = data_len + 12
2       2     Command ID
4       2     Start index
6       2     Count
8       2     Data length
10      N     Data bytes
10+N    2     CRC16
```

### Response Packet

Responses follow a similar structure with one important difference: the `item_size` field represents the **total number of items** in the response, not the per-item byte size.

```
Offset  Size  Field
──────  ────  ─────────────────────
0       2     Total response length (LE uint16)
2+      8     Command block header (repeating):
              [2] Command ID
              [2] Start index
              [2] Item count (total items in response)
              [2] Data length (bytes)
              [N] Payload data
...           More command blocks
N       2     CRC16 checksum
```

**Parsing a response:**
1. Read total length from bytes 0–1
2. Set `end = total_length - 2` (exclude CRC)
3. Start at offset 2
4. Read command header (8 bytes): cmd, start, item_size, data_len
5. Read `data_len` bytes of payload
6. Advance position by `8 + data_len`
7. Repeat until position >= end

### Acknowledgement Responses

When a command is acknowledged without data (e.g., login success, keypress accepted), the response block has `data_len = 0`:

```
CMD 1, start=1, item_size=0, data_len=0  → Login successful
CMD 11, start=1, item_size=0, data_len=0 → Keypress accepted
CMD 6, start=1, item_size=0, data_len=0  → Output control accepted
```

---

## CRC16

The protocol uses a CRC16 lookup table with initial value `0xFFFF`.

```python
def calc_crc16(data, count):
    crc = 0xFFFF
    for i in range(count):
        crc = CRC16_TABLE[(data[i] ^ crc) & 0xFF] ^ (crc >> 8)
    return crc & 0xFFFF
```

The CRC is computed over all bytes from offset 0 to `total_length - 2`, and stored in the final 2 bytes of the packet.

The full 256-entry CRC16 table is provided in `const.py`.

---

## Command Reference

### Authentication & Info

| CMD | Name | Direction | Description |
|-----|------|-----------|-------------|
| 1   | Password | Req/Resp | Login. Data = ASCII password bytes. Empty response = success. |
| 2   | Panel Info | Req/Resp | Returns panel type, version, variant. |
| 3   | Panel State | Req/Resp | Returns log pointer, user number, user area bitmask. |
| 20  | System Config | Req/Resp | Returns sub-commands with panel capabilities. |
| 99  | Error | Resp only | Error response. Data[0] = error code. |

**Error codes:**
- `3` = Password failed
- `5` = Command not supported
- `65503` = Authorisation key failed (cloud only)

### System Config Sub-Commands (CMD 20)

The CMD 20 response contains nested TLV blocks:

| Sub-CMD | Description |
|---------|-------------|
| 65 | Max areas (1 byte) |
| 80 | Part arm text count |
| 83 | Panel serial number (ASCII, null-terminated) |
| 85 | Panel UID (raw bytes) |
| 86 | [max_remote_outputs, max_cameras, part_arm_mask] |
| 90 | Max zones (1 byte) |

### Status Queries

| CMD | Name | Description |
|-----|------|-------------|
| 1110 | Zone Types | 1 byte per zone. See Zone Type table. |
| 1114 | Max Zones | Returns max zone count |
| 1120 | Zone Texts | Null-terminated ASCII strings, max 15 per query. |
| 1130 | Zone Wiring | Wiring type per zone |
| 1140 | Zone Areas | 1 byte per zone, bitmask of assigned areas |
| 1141 | Max Areas | Returns max area count |
| 1150 | Zone Bypass | Bypass state per zone |
| 2110 | Area Texts | Null-terminated ASCII area names |
| 2120 | Area Arm Mode | Arm mode per area |
| 2150 | Area Arm Attributes | Arm attributes per area |
| 3510 | System Text | Panel system text messages |
| 3514 | Max System Text | Max system text message count |
| 3520 | Remote Output Texts | Null-terminated ASCII output names |
| 3524 | Max Remote Outputs | Returns max remote output count |
| 3540 | Part Arm Texts | Null-terminated ASCII part arm mode names (up to 3) |
| 7610 | UDL Option | UDL configuration option |
| 8120 | User Type | User type for given user number |

### Live Status Queries

| CMD | Name | Item Size | Description |
|-----|------|-----------|-------------|
| 10110 | Zone Status | 2 bytes/zone | Bit 0 = active/open, Bit 1 = tamper |
| 10120 | Zone Timers | 2 bytes/zone | Seconds since last activity |
| 10160 | Zone Status 2 | Variable | Extended zone status |
| 10320 | System Output State | 1 byte/index | 65-byte array, each byte is area bitmask |
| 10340 | Remote Output State | 1 byte/output | 0 = off, non-zero = on |

### Control Commands

| CMD | Name | Data Format | Description |
|-----|------|-------------|-------------|
| 6   | Control Output | `[id_lo, id_hi, new_state, action]` | Toggle remote output |
| 9   | LCD | - | Request LCD display data |
| 10  | Keypad Char | ASCII bytes | Send characters to keypad |
| 11  | Keypress | `[key_code, area_lo, area_mid, area_hi]` | Send arm/disarm command |
| 12  | Event Log | - | Request event log entries |
| 23  | Fog Control | `[status_lo, status_hi, timer, mode]` | Fog device control |

---

## System Output State Array

The system output state (CMD 10320) is a 65+ byte array where each byte is a **bitmask of areas**. Bit 0 = Area 1, Bit 1 = Area 2, etc.

### Key Indices

| Index | Name | Description |
|-------|------|-------------|
| 0 | Not Used | - |
| 1 | AC Fault | Mains power fault |
| 2 | ATS Fault | ATS communication fault |
| 3 | System Open | System is open/unsealed |
| 4 | Just Disarmed | Recently disarmed |
| 5 | **Armed** | Area is armed (full or part) |
| 6 | **Part Armed** | Area is stay/part armed |
| 7 | Armed Alarm | Armed with alarm active |
| 8 | Bell | Bell/siren active |
| 9 | Strobe | Strobe light active |
| 10 | **Alarm** | System alarm active |
| 11 | Confirmed Alarm | Confirmed intruder alarm |
| 12 | Confirmed PA | Confirmed panic alarm |
| 13 | Alarm Abort | Alarm abort in progress |
| 14 | Fire | Fire alarm |
| 15 | PA | Panic alarm |
| 16 | Duress | Duress alarm |
| 17 | 24 Hour | 24-hour alarm |
| 18 | Medical | Medical alarm |
| 19 | Tamper | Tamper detected |
| 20 | **Ready** | System ready to arm |
| 21 | Trouble | System trouble condition |
| 22 | Alert | System alert |
| 23 | Bypass | Zones bypassed |
| 31 | Battery Fault | Battery fault detected |
| 40 | **In Exit** | Exit timer running (arming) |
| 41 | **In Entry** | Entry timer running |
| 42 | In 2nd Entry | Second entry timer |
| 43 | **In Alarm** | Currently in alarm state |
| 48 | Call Engineer | Engineer visit required |
| 57 | **Panel AC On** | AC mains power present |
| 59 | Arming Failed | Last arm attempt failed |
| 61 | **Part Arm 1** | Part arm mode 1 (Stay 1) active |
| 62 | **Part Arm 2** | Part arm mode 2 (Stay 2) active |
| 63 | **Part Arm 3** | Part arm mode 3 (Stay 3) active |

### Alarm State Derivation

To determine the alarm state for a given area (area index 0-based):

```python
bit = 1 << area_index

if sos[10] & bit:          # SysAlarm
    state = "triggered"
elif sos[5] & bit:         # SysArmed
    if sos[6] & bit:       # SysStayArmed (Part Armed)
        state = "armed_home"
        # Check which part mode:
        if sos[61] & bit: part = 1
        elif sos[62] & bit: part = 2
        elif sos[63] & bit: part = 3
    else:
        state = "armed_away"
elif sos[40] & bit:        # InExit
    state = "arming"
elif sos[41] & bit:        # InEntry
    state = "pending"
else:
    state = "disarmed"
```

---

## Keypress Codes

| Code | Action |
|------|--------|
| 0 | Full Arm |
| 1 | Part Arm 1 |
| 2 | Part Arm 2 |
| 3 | Part Arm 3 |
| 4 | Disarm |
| 99 | Reset |
| 112 | Panic Alarm |

**Keypress packet data format:** `[key_code, area_mask_byte0, area_mask_byte1, area_mask_byte2]`

The area mask is a 24-bit bitmask: bit 0 = area 1, bit 1 = area 2, etc.

---

## Output Control

Remote outputs are controlled via CMD 6 with a 4-byte data payload:

```
Byte 0-1: Output ID (LE uint16) = 2000 + output_index (0-based)
Byte 2:   New state (current_state XOR 1 to toggle)
Byte 3:   Action type (2 = toggle output)
```

---

## Zone Types

| ID | Type | HA Device Class |
|----|------|-----------------|
| 0 | Not Used | - |
| 1 | Final Exit 1 | opening |
| 2 | Final Exit 2 | opening |
| 3 | Entry Route | opening |
| 4 | Intruder | motion |
| 5 | Perimeter | door |
| 6 | Fire | smoke |
| 7 | PA Silent | safety |
| 8 | PA Audible | safety |
| 9 | PA Confirmed | safety |
| 10 | PA Confirmed Silent | safety |
| 11 | Disarmed PA Silent | safety |
| 12 | Disarmed PA Audible | safety |
| 13 | Medical | problem |
| 14 | 24 Hour | problem |
| 15 | 24 Hour (Int) | problem |
| 16 | Tamper | tamper |
| 17 | Exit Terminator | opening |
| 29 | Flood 24 Hour | moisture |
| 30 | CO 24 Hour | gas |
| 33 | RTE / Door Bell | occupancy |

---

## Panel Types

| Panel ID | Model | Z-Variant |
|----------|-------|-----------|
| 40 | WCP40 | N/A |
| 110 | CP10 | ZP10 |
| 120 | CP20 | ZP20 |
| 140 | CP40 | ZP40 |
| 160 | EP100 | ZP100 |
| 200 | CP200 | N/A |

Z-variants are identified when `panel_var == 1` in the CMD 2 response (byte offset 4).

---

## Connection State Machine

A typical session follows these stages:

### Stage 1: Login
```
Send: [CMD 1 (password)] + [CMD 2 (panel info)] + [CMD 3 (state)] + [CMD 20 (config)]
Recv: Access granted + panel type/version + user info + system config
```

### Stage 2: Configuration
```
Send: [CMD 1114 (max zones)] + [CMD 1141 (max areas)] + [CMD 3524 (max outputs)]
      + [CMD 8120 (user type)] + [CMD 7610 (UDL option)]
Recv: Panel capabilities and limits
```

### Stage 3: Initial Data Load
```
Send: [CMD 1110 (zone types)] + [CMD 1140 (zone areas)] + [CMD 2110 (area names)]
Send: [CMD 1120 (zone names)] — batches of 15
Send: [CMD 3520 (output names)] + [CMD 10340 (output states)]
Send: [CMD 3540 (part arm texts)] + [CMD 2150 (area arm attrs)]
      + [CMD 10320 (sys output state)] + [CMD 3 (panel state)]
      + [CMD 10110 (zone status)]
```

### Stage 4: Polling (every 2 seconds)
```
Send: [CMD 10320 (sys output state)] + [CMD 3 (panel state)]
      + [CMD 10110 (zone status)] + [CMD 10120 (zone timers)]
Recv: Updated status data
```

The zone names query (CMD 1120) is limited to 15 zones per request due to UDP packet size constraints. For panels with more zones, multiple batches are sent.

---

## Cloud Relay Protocol

When communicating through the cloud relay, packets undergo two additional transformations:

### 1. XOR Encryption (UpdateTxData)

The raw panel packet is encrypted using an XOR stream cipher:

```
1. Generate random seed byte (0-255)
2. Create header: [seed, 0x09, serial_num_xor[18], crc16_of_payload[2]]
3. XOR serial number bytes with AddInCrc(counter) stream
4. XOR payload bytes with AddInCrc(counter) stream
5. XOR payload again with authorisation key (repeating)
```

**AddInCrc key derivation:**
```python
def AddInCrc(data):
    if data == 0:
        return 0xA5  # 165
    return ((CRC16_TABLE[data] >> 8) + CRC16_TABLE[data]) & 0xFF
```

The resulting encrypted packet is 20 bytes longer than the original (1 seed + 1 marker + 18 serial + 2 CRC prefix).

### 2. Server Wrapping (LoadServerData)

The encrypted packet is wrapped with server addressing:

```
[total_length (2 LE)]
[0x0F, auth_key_len, auth_key_bytes...]  (if auth key present)
[0x0D, serial_len, serial_bytes...]      (server endpoint)
[0x0B, payload_len_lo, payload_len_hi, payload...]  (panel data)
[0xAA]  (end marker)
```

Server command bytes:
- `0x0B` (11) = Server-to-panel data
- `0x0D` (13) = Set endpoint (serial number)
- `0x0F` (15) = Authorisation key

### Server Response Handling

Server responses may contain additional framing:
- `90` = Invalid IP / endpoint not found
- `91` = Authorisation failed
- `92` = Authorisation key failed
- `34` = Logo details response

The actual panel response is extracted from the server wrapper before being processed by `ProcessRxBuff`.

---

## Practical Notes

- **UDP packet size:** Keep request packets under ~200 bytes. The panel allocates a 200-byte buffer for requests.
- **Response timing:** The panel typically responds within 10–50ms on LAN. Allow 3–5 seconds timeout for reliability.
- **Settle time:** After receiving the first response datagram, wait ~200ms for any additional packets before processing.
- **Polling interval:** The mobile app polls every ~2 seconds in normal operation. This is sufficient for near-real-time status updates.
- **Zone name batching:** Request at most 15 zone names per query to avoid oversized response packets.
- **Multi-command packets:** Combining multiple queries into a single packet reduces round trips. The panel responds with all requested data in a single response (or occasionally split across 2 datagrams).
- **Area bitmask:** All area-related commands use a bitmask where bit N corresponds to area N+1. A panel with 2 areas uses bits 0 and 1 (mask `0x03`).
- **No session tokens:** The protocol is stateless after login. Each polling packet stands alone — there is no session ID or sequence number.
- **Re-login:** If the panel stops responding (e.g., after a power cycle), simply re-send the login packet. There is no explicit "logout" command.
