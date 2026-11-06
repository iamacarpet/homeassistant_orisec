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
├── throttled_log.py      # Rate-limited logging for per-poll/per-packet messages
├── diagnostics.py        # Diagnostics download (link state, counters, history)
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

**Extra attributes:** ready, trouble, bypass, bell, ac_fault, battery_fault, active_part_arm, state_confirmed, state_cached_since

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

**Panel Status sensor:** Shows online/offline with attributes for panel type, version, serial, AC power, trouble state, part-arm mode names and the link diagnostics. Unlike other entities it is always available, so the reason for an outage stays visible.

## Coordinator

The `OrisecCoordinator` extends Home Assistant's `DataUpdateCoordinator` and manages:

1. **Connection lifecycle** — connect, login, reconnect on failure
2. **Initial data load** — zone types, names, areas, area names, output names, part-arm texts
3. **Polling** — every 5 seconds (2 while a keypad card is subscribed):
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

A poll the panel doesn't answer (after retries) is tolerated for `POLL_FAILURE_GRACE` (30 s since the last good poll): entities stay available on the last known state. Past that, or immediately if the panel refuses the connection or answers with an error instead of the system output state block (e.g. an expired login), the coordinator keeps the last known state, marks entities unavailable, and starts a background reconnect loop with backoff. Reconnects only re-run stages 1, 2 and a status read; zone/area names are not re-downloaded once loaded. Each reconnect attempt closes the UDP socket and opens a fresh one on the same fixed local port, waiting for the old socket to release the port first, so the panel still sees the same client while any host-side socket state (e.g. a source address cached before the host's IP changed) is discarded. Polls that fail within the grace period keep the existing socket.

Requests share one UDP socket and replies carry no request id, so `OrisecConnection` serialises requests with a lock and matches replies by command ID: a datagram containing none of the requested command blocks (or `CMD 99`) is a late reply to an earlier request and is dropped. Once the panel has sent one reply with a valid CRC, replies with a bad length or CRC are dropped too. Collection ends as soon as every requested block has arrived, or `settle_time` after the first reply.

Commands that change panel state (keypress, output toggle, keypad characters) are sent once, never retried, because a lost acknowledgement would otherwise press the key twice. An unacknowledged arm/disarm/output command raises `HomeAssistantError` and triggers a state refresh. A command answered with `CMD 99` also raises `HomeAssistantError`, since the panel rejected it and nothing changed.

Arm/disarm and output commands log in again just before they are sent. The login is panel-wide and status polls are answered whatever session is active, so a long-lived connection never notices that the ControlPlus2 app has logged in as another user, or that the session has lapsed. Without a fresh login, the command would run under that other session (or none) and be rejected.

The panel answers any number of client endpoints, but sends each reply to whichever endpoint sent to it last, and holds a single login session shared by all of them (tested on a CP20). When another local client (the ControlPlus2 app in local mode) sends during the ~0.1 s the panel takes to answer, our reply goes to that client and our request is dropped; nothing arrives late. Read attempts therefore wait only `UDP_TIMEOUT` (1 s; the panel answers in 0.1–0.3 s) before retrying, while state-changing commands, which are sent once, wait `COMMAND_TIMEOUT` (3 s) for their ack.

The local port is derived from the panel address (`local_port_for`, 21000–21999) and kept across reconnects and restarts. If it can't be bound, `connect()` raises `LocalPortInUseError` instead of falling back to a random port: the port is only held by another client of the same panel on the same host, which would compete for replies. The error is retried like any other connection failure, logged as a warning, and shown as `port_in_use` in the config flow (an ICMP refusal shows as `panel_refused`). State-changing commands require a logged-in session (`coordinator.connected`), not merely an open socket.

### Diagnostics

`OrisecConnection` keeps two sets of counters:

- `stats`, problem counters that move only when something goes wrong: `bind_failures`, `failed_requests`, `timeouts`, `retries`, `refused`, `udp_errors`, `stale_replies_dropped` and `corrupt_replies_dropped`.
- `traffic`, totals that rise on every poll: `requests`, `packets_sent` and `replies_received`.

It also tracks `consecutive_timeouts`, the times of the last request and the last accepted reply, the time the last request took to answer, and the socket's real `local_endpoint` (`getsockname` on the connected socket, so it shows the IP the OS routes from) and `remote_endpoint`.

The counters follow these rules:

- An attempt counts as a timeout when no reply is *accepted* in time, even if stale or corrupt datagrams arrived.
- A datagram that arrives while no request is waiting for it counts as stale when the next attempt starts.
- A network error other than a refusal counts under `udp_errors`, not `timeouts`.

The coordinator adds:

- a status: `connected`; `degraded` (failed polls ridden out on the last state); `reconnecting`; `disconnected`.
- `state_confirmed` and `state_cached_since`, from the time the status block was last applied.
- `session_errors`.
- the time and reason of the last transition to unavailable and of the last reconnect attempt.
- a bounded event history (`DIAGNOSTIC_HISTORY_SIZE`).

Reasons are prefixed with a `failure_category()`: `no_response`, `refused`, `udp_error`, `port_in_use`, `session_error`, `login_rejected`, `invalid_reply`, `socket_error`. Each reconnect attempt's reason is the outage for the first attempt, then the previous attempt's failure. After a failed attempt the reconnect loop calls `async_update_listeners()`, because HA doesn't notify entities about repeated failed polls.

The Panel Info sensor's attributes (`connection_stats`) are kept to values that change only when something goes wrong, so a healthy link doesn't write a new state every poll. `diagnostics()`, served by `diagnostics.py`, adds the traffic totals, timestamps, settings and history; the PIN is redacted from the entry data.

Per-poll and per-packet log messages go through `ThrottledLog`, which lets each kind through at most once per `DEBUG_LOG_INTERVAL` (60 s) and reports how many it skipped. Transitions are logged unthrottled. Logs carry command IDs only, never request payloads, which contain the PIN and key presses.

The panel configuration (stage 3 metadata) is cached in HA storage (`.storage/orisec.<entry_id>`). When a cache exists, setup builds entities from it without contacting the panel and connects in the background; the first successful connection refreshes the cache. Only the first setup (no cache) blocks on the panel and raises `ConfigEntryNotReady` if it is unreachable.

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
- **Settle time:** up to 200ms after the first response for any remaining requested blocks
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
