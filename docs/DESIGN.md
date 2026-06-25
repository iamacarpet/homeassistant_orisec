# Orisec ControlPlus2 — Home Assistant Integration Design

## Overview

This integration provides local LAN control of Orisec ControlPlus2 alarm panels via Home Assistant. It communicates directly with the panel over UDP on port 20202, requiring no cloud services or internet connection.

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                 Home Assistant                       │
│                                                     │
│  ┌──────────┐   ┌─────────────┐   ┌─────────────┐ │
│  │  Config   │──▶│ Coordinator │──▶│  Protocol   │ │
│  │   Flow    │   │  (Polling)  │   │  (UDP I/O)  │ │
│  └──────────┘   └──────┬──────┘   └──────┬──────┘ │
│                        │                  │         │
│            ┌───────────┼───────────┐      │         │
│            ▼           ▼           ▼      │         │
│      ┌──────────┐ ┌─────────┐ ┌──────┐   │         │
│      │  Alarm   │ │ Binary  │ │Switch│   │         │
│      │  Panel   │ │ Sensor  │ │      │   │         │
│      └──────────┘ └─────────┘ └──────┘   │         │
│      ┌──────────┐                        │         │
│      │  Sensor  │                        │         │
│      └──────────┘                        │         │
│                                          │         │
└──────────────────────────────────────────┼─────────┘
                                           │ UDP :20202
                                    ┌──────┴──────┐
                                    │   Orisec    │
                                    │   Panel     │
                                    └─────────────┘
```

## File Structure

```
custom_components/orisec/
├── __init__.py           # Entry setup/teardown
├── manifest.json         # Integration metadata
├── config_flow.py        # UI-based configuration
├── const.py              # All protocol constants
├── coordinator.py        # DataUpdateCoordinator (polling + state)
├── protocol.py           # UDP transport, packet I/O, response parsing
├── alarm_control_panel.py # Per-area alarm entities + part-arm entities
├── binary_sensor.py      # Per-zone binary sensors (state + tamper)
├── switch.py             # Remote output switches
├── sensor.py             # Panel status sensor
├── strings.json          # UI strings
└── translations/
    └── en.json           # English translations
```

## Entity Model

### Alarm Control Panel

One primary entity per area (filtered by user's authorised area bitmask):

| State | Derivation |
|-------|-----------|
| triggered | `sys_output_state[10] & area_bit` (SysAlarm) |
| armed_away | `sos[5] & bit` AND NOT `sos[6] & bit` |
| armed_home | `sos[5] & bit` AND `sos[6] & bit` (Part Armed) |
| arming | `sos[40] & bit` (exit timer) |
| pending | `sos[41] & bit` (entry timer) |
| disarmed | None of the above |

**Part-arm entities:** For each area, additional alarm entities are created for each available part-arm mode (up to 3, controlled by `part_arm_mask`). Each shows `armed_home` when its specific part mode is active.

**Commands:**
- `arm_away` → Keypress code 0 (Full Arm)
- `arm_home` → Keypress code 1/2/3 (Part Arm 1/2/3)
- `disarm` → Keypress code 4

**Extra attributes:** ready, trouble, bypass, bell, ac_fault, battery_fault, active_part_arm

### Binary Sensors

Two entities per used zone (zone type ≠ 0, has a name):

1. **Zone state sensor** — `is_on` when `zone_status[i] & 0x01` (active/open)
2. **Zone tamper sensor** — `is_on` when `zone_status[i] & 0x02` (disabled by default)

Device class is mapped from zone type:
- Intruder → `motion`
- Perimeter → `door`
- Fire → `smoke`
- Final Exit / Entry Route → `opening`
- Flood → `moisture`
- CO → `gas`
- PA types → `safety`

### Switches

One entity per remote output. State read from `rem_output_state[i]`. Toggle via CMD 6 with output ID = 2000 + index.

### Sensors

**Panel Status sensor:** Shows online/offline with attributes for panel type, version, serial, AC power, trouble state, and part-arm mode names.

## Coordinator

The `OrisecCoordinator` extends Home Assistant's `DataUpdateCoordinator` and manages:

1. **Connection lifecycle** — connect, login, reconnect on failure
2. **Initial data load** — zone types, names, areas, area names, output names, part-arm texts
3. **Polling** — every 2 seconds:
   - System output states (65 bytes — alarm/arm status)
   - Panel state (user info, log pointer)
   - Zone status (open/tamper per zone)
   - Zone timers (alternating polls)
   - Remote output states (every 3rd poll)
4. **Event detection** — fires `orisec_alarm_triggered` on HA event bus when alarm transitions from inactive to active

### Connection State Machine

```
Stage 0: Disconnected
Stage 1: Login (password + panel info + config)
Stage 2: Configuration (max zones/areas/outputs, user type)
Stage 3: Initial data load (zone names, types, areas, outputs, part arm texts)
Stage 4: Polling (continuous 2-second interval)
```

On communication failure, the coordinator disconnects and attempts reconnection on the next poll cycle.

## Protocol Layer

`protocol.py` provides:

- **Packet construction:** `load_udl_pkt`, `add_udl_pkt`, `load_data_pkt`, `build_password_packet`, `build_keypress_packet`, `build_output_toggle_packet`
- **CRC16 computation:** Lookup table, init 0xFFFF
- **Response parsing:** `parse_response` / `parse_responses` into `ParsedResponse` dataclass
- **UDP transport:** `OrisecConnection` class with asyncio datagram protocol

The protocol layer is independent of Home Assistant and can be used standalone for testing.

## Config Flow

Single-step UI flow:
1. User enters: Panel IP, Port (default 20202), Password
2. Integration attempts login to validate credentials
3. On success, creates config entry with panel serial as unique ID

Error handling:
- Wrong password → "Invalid password" error
- No response → "Cannot connect" error
- Already configured → Abort

## Communication Details

- **Transport:** UDP, connectionless
- **Timeout:** 3 seconds per request
- **Settle time:** 200ms after first response to collect additional datagrams
- **Poll interval:** 2 seconds
- **No encryption** needed for local LAN communication
- **No push notifications** — status changes are detected by polling
- **Zone names:** Queried in batches of 15 (protocol limitation)

## Events

The integration fires Home Assistant events on alarm state transitions:

```yaml
event_type: orisec_alarm_triggered
data:
  area: 1            # Area number (1-based)
  area_name: "Home"  # Area name from panel
  fire: false         # Fire alarm active
  pa: false           # Panic alarm active
  bell: true          # Bell/siren active
```

## Testing

### Unit Tests

```bash
python3 -m pytest tests/test_protocol_unit.py -v
```

Tests CRC16 computation, packet construction, response parsing, and alarm state derivation without requiring a physical panel.

### Live Read-Only Tests

```bash
python3 -m tests.test_live_readonly --host PANEL_IP --password PIN -v
```

Performs comprehensive read-only queries against a live panel: login, panel info, system config, zone types/names/status/areas, area names, remote outputs, part arm texts, alarm state derivation, zone timers, and multi-query packets. **Does not modify any panel state.**

## Installation

1. Copy `custom_components/orisec/` to your Home Assistant config directory
2. Restart Home Assistant
3. Go to Settings → Devices & Services → Add Integration → "Orisec ControlPlus2"
4. Enter panel IP, port (20202), and password
5. Entities are auto-created for all areas, zones, and outputs
