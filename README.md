# Orisec ControlPlus2 — Home Assistant Integration

Local LAN integration for Orisec ControlPlus2 alarm panels (CP10, CP20, CP40, CP200, EP100, and Z-variants).

Communicates directly with the panel over UDP on port 20202 — no cloud, no internet dependency, no latency.

## Features

- **Alarm control** — Full Set, Part Set (1/2/3), and Disarm per area, with the panel's own arm-mode names
- **Virtual keypad** — Real-time LCD display emulation and full 24-button keypad via a dedicated sidebar panel
- **Part-arm modes** — Up to 3 part-arm modes (Home/Night/Vacation) driven by the panel's own programmed names
- **Zone sensors** — Binary sensors for every configured zone with auto-assigned device classes
- **System sensors** — AC power, battery fault, tamper, bell active, and trouble indicators
- **Tamper detection** — Per-zone tamper sensors (disabled by default to reduce clutter)
- **Remote outputs** — Switch entities for all remote outputs (disabled by default)
- **Panel diagnostics** — Sensor with panel type, version, serial, connection state, and link-quality counters (timeouts, retries, dropped replies, connection drops). It stays available while the panel is offline and shows why. A diagnostics download adds traffic totals, timestamps, the UDP endpoints and a history of outages and reconnect attempts (see [Diagnosing unavailability](#diagnosing-unavailability))
- **Alarm events** — Fires `orisec_alarm_triggered` / `orisec_alarm_cleared` / `orisec_state_changed` on the HA event bus
- **Polling** — 5-second update interval via lightweight UDP packets (2 seconds while the keypad card is open)
- **Auto-reconnect** — Brief packet loss is ridden out on the last known state for up to 30 seconds; after that, or as soon as the panel rejects the session, entities go unavailable and the integration logs back in automatically in the background. A poll the panel doesn't answer is never treated as "disarmed"
- **Safe commands** — Arm, disarm, output and keypad commands are sent exactly once; if the panel doesn't acknowledge, HA reports it rather than pressing the key again
- **Survives restarts** — The panel's zone/area configuration is cached, so after an HA restart entities are created immediately and come online as soon as the panel answers
- **Custom Lovelace cards** — `orisec-alarm-panel-card` and `orisec-keypad-card` auto-registered; shows your panel's arm-mode names
- **Sidebar panel** — Auto-registered "Orisec" sidebar item with alarm controls and keypad in one page

## Supported Panels

| Model | Zones | Areas |
|-------|-------|-------|
| CP10 / ZP10 | 10 | 1 |
| CP20 / ZP20 | 20 | 2 |
| CP40 / ZP40 | 40 | 4 |
| CP200 | 200 | 8 |
| EP100 / ZP100 | 100 | 4 |
| WCP40 | 40 | 4 |

## Requirements

- Orisec ControlPlus2 panel on your local network
- Panel IP address and UDP port (default: 20202)
- Panel password (the same PIN used in the mobile app)
- Home Assistant **2024.7.0** or later

## Installation

### HACS (Recommended)

1. In HACS, go to **Integrations** → three-dot menu → **Custom repositories**
2. Add this repository URL with category **Integration**
3. Search for "Orisec ControlPlus2" and install
4. Restart Home Assistant

### Manual

```bash
cp -r custom_components/orisec /config/custom_components/orisec
```

Restart Home Assistant after copying.

## Configuration

1. Go to **Settings** → **Devices & Services** → **Add Integration**
2. Search for "Orisec ControlPlus2"
3. Enter:
   - **Panel IP Address** — your panel's LAN IP
   - **Panel Port** — `20202` (default)
   - **Panel Password** — your panel PIN
4. Click Submit

The integration validates credentials during setup and raises a clear error if the password is rejected.

## Entities Created

### Alarm Control Panel

One entity per area named "Alarm" (or "{area_name} Alarm" for multi-area panels). It appears in the **Security** section of the HA dashboard automatically.

| Entity | Description |
|--------|-------------|
| `alarm_control_panel.alarm` | Alarm control for the area |

**Supported arm modes** (shown as buttons in the alarm card):

| HA Mode | Maps to | Default button label |
|---------|---------|----------------------|
| `arm_away` | Full Set | "Full Set" |
| `arm_home` | Part Set 1 | Panel's programmed name (e.g. "Night") |
| `arm_night` | Part Set 2 | Panel's programmed name (e.g. "Bedtime") |
| `arm_vacation` | Part Set 3 | Panel's programmed name |

Part modes are only shown if the panel has them configured (`part_arm_mask`). `code_arm_required` is `false` — no PIN needed from HA.

**States:** `disarmed`, `armed_away` (Full Set), `armed_home/night/vacation` (Part Set 1/2/3), `arming` (exit timer), `pending` (entry timer), `triggered`

**Attributes:** `ready`, `trouble`, `bypass`, `bell`, `ac_fault`, `battery_fault`, `home_mode`, `night_mode`, `vacation_mode`

### Binary Sensors — System

These appear in the **Security** / main dashboard sections.

| Entity | Device class | Description |
|--------|-------------|-------------|
| `binary_sensor.ac_power` | Plug | Mains AC present |
| `binary_sensor.battery_fault` | Battery | Battery problem detected |
| `binary_sensor.tamper` | Tamper | Panel tamper |
| `binary_sensor.bell_active` | Sound | Bell/siren sounding |
| `binary_sensor.trouble` | Problem | Panel trouble condition |

### Binary Sensors — Zones

| Entity | Description |
|--------|-------------|
| `binary_sensor.{zone_name}` | Zone state — on when active/open |
| `binary_sensor.{zone_name}_tamper` | Zone tamper (disabled by default) |

Device classes are auto-assigned from zone type: `motion`, `door`, `opening`, `smoke`, `moisture`, `gas`, `safety`, `tamper`, `occupancy`, `problem`.

**Note:** Final Exit and Entry Route zone types default to `motion` as these are almost always PIR sensors on Orisec installations.

**Attributes:** `zone_number`, `zone_type`, `raw_status`, `bypassed`, `activity_timer`

### Switches

| Entity | Description |
|--------|-------------|
| `switch.{output_name}` | Remote output toggle (disabled by default) |

Remote outputs (labelled "Remote 1–5" if unnamed) are the panel's relay outputs — these can be enabled individually from the entity registry if needed.

### Sensors

| Entity | Description |
|--------|-------------|
| `sensor.panel_info` | Online/offline (DIAGNOSTIC). Stays available while the panel is offline, so its attributes can say why |

**Attributes:** `panel_type`, `panel_version`, `serial`, `host`, `max_zones`, `max_areas`, `max_remote_outputs`, `part_arm_mask`, `ac_power`, `trouble`, `engineer_required`, `area_N_state`, `area_N_name`, `part_arm_names`, plus the connection attributes described in [Diagnosing unavailability](#diagnosing-unavailability)

Alarm entities also carry `state_confirmed` (false while failed polls are being ridden out on the last known state) and `state_cached_since` (when the panel last confirmed the state shown).

## Custom Lovelace Cards

The integration auto-registers two custom Lovelace cards.

### Alarm Panel Card

Replaces HA's generic "Away / Home / Night / Vacation" button labels with the names programmed into your panel.

```yaml
type: custom:orisec-alarm-panel-card
entity: alarm_control_panel.alarm
name: My Alarm   # optional
```

The card shows the current state (Disarmed / Full Set / Set – {name} / Setting… / Entry delay… / Alarm!) with a colour-coded badge and blinking animation for active states.

### Keypad Card

A virtual keypad with live LCD display. Can be added to any dashboard.

```yaml
type: custom:orisec-keypad-card
name: Panel Keypad   # optional
```

The card auto-discovers the panel entry and provides a 4-line LCD display (updated every 2 seconds) with the full 24-button keypad layout matching the physical panel: digits 0–9, Fire, PA, Accept, Yes, No, Omit, Clear, Reset, and arrow navigation.

LCD polling only activates while the card is visible and stops automatically when you navigate away.

## Sidebar Panel

The integration registers an **Orisec** item in the HA sidebar automatically on setup. This provides a dedicated full-page interface combining:

- **Alarm status** — current arm state, ready/trouble/bypass indicators, arm/disarm buttons
- **Virtual keypad** — live LCD display and full button grid

Access it from the sidebar or via the "Visit" link on the device page in Settings → Devices & Services.

## Events

The integration fires three event types on the HA event bus:

### `orisec_alarm_triggered`

Fired when an area enters alarm state.

```yaml
event_data:
  area: 1
  area_name: "Home"
  fire: false
  pa: false
  bell: true
```

### `orisec_alarm_cleared`

Fired when an area exits alarm state.

```yaml
event_data:
  area: 1
  area_name: "Home"
```

### `orisec_state_changed`

Fired whenever an area's arm state changes (e.g. disarmed → armed_away).

```yaml
event_data:
  area: 1
  area_name: "Home"
  old_state: "disarmed"
  new_state: "armed_away"
```

## Automations

### Alarm triggered notification

```yaml
automation:
  - alias: "Alarm Triggered Alert"
    trigger:
      - platform: event
        event_type: orisec_alarm_triggered
    action:
      - service: notify.mobile_app
        data:
          title: "ALARM"
          message: >
            {{ trigger.event.data.area_name }} alarm triggered!
            {% if trigger.event.data.fire %}(Fire){% endif %}
            {% if trigger.event.data.pa %}(PA){% endif %}
```

### Arm at bedtime

```yaml
automation:
  - alias: "Part Set at Midnight"
    trigger:
      - platform: time
        at: "00:00:00"
    action:
      - service: alarm_control_panel.alarm_arm_home
        target:
          entity_id: alarm_control_panel.alarm
```

### Notify on arm state change

```yaml
automation:
  - alias: "Alarm State Changed"
    trigger:
      - platform: event
        event_type: orisec_state_changed
    action:
      - service: notify.mobile_app
        data:
          title: "Alarm"
          message: >
            {{ trigger.event.data.area_name }}: {{ trigger.event.data.old_state }}
            → {{ trigger.event.data.new_state }}
```

### Zone activity light (while disarmed)

```yaml
automation:
  - alias: "Hall Motion Light"
    trigger:
      - platform: state
        entity_id: binary_sensor.hall
        to: "on"
    condition:
      - condition: state
        entity_id: alarm_control_panel.alarm
        state: "disarmed"
    action:
      - service: light.turn_on
        target:
          entity_id: light.hallway
```

## Testing

### Unit tests (no panel needed)

```bash
python3 -m pytest tests/test_protocol_unit.py -v
```

### Live read-only test (against a real panel)

```bash
python3 -m tests.test_live_readonly --host 192.168.1.100 --password YOUR_PIN -v
```

This performs comprehensive read-only queries and does **not** arm, disarm, or modify any panel state. Running it while Home Assistant (or the app in local mode) is polling the panel works, but both sides will see occasional timeouts while it runs.

## How It Works

The integration communicates with the panel using its native binary UDP protocol:

1. **Login** — Sends password, receives panel info, capabilities, and user area mask
2. **Setup** — Queries zone types, names, area names, output names, part-arm mode names (cached in HA storage, so later restarts don't wait for the panel)
3. **Poll** — Every 5 seconds (2 while the keypad card is open): reads system output states (arm/alarm/ready flags), zone status (open/tamper), zone timers, and remote output states in a single multi-query
4. **Commands** — Arm/disarm sends keypress codes; output toggle sends control commands

All communication is local UDP. See [docs/PROTOCOL.md](docs/PROTOCOL.md) for full protocol details.

### Sharing the panel with the ControlPlus2 app

The panel accepts requests from any number of local clients, but it sends each reply to whichever client sent it something most recently. If the ControlPlus2 app in **local** mode (or a second Home Assistant) sends a request while the panel is still answering Home Assistant's (a window of roughly 0.1 s), Home Assistant's reply goes to the app and Home Assistant's request is lost; the same happens the other way round. Login is also shared: the panel holds one logged-in session, used by every client. The app's **cloud** mode goes through Orisec's relay and doesn't compete on the local network.

The integration copes with this. Each attempt waits at most 1 second for a reply (the panel normally answers within 0.3 s), lost polls are retried, and up to 30 seconds of failed polls are ridden out on the last known state. Because another client can replace the shared login (or it can lapse) while status polls keep working, Home Assistant logs in again with its PIN just before each arm, disarm or output command. Those commands are sent only once and wait up to 3 seconds for an acknowledgement; if a busy app takes that acknowledgement, Home Assistant reports that the command may not have been applied, rather than pressing the key again.

Home Assistant always connects from the same local UDP port (21000–21999, derived from the panel's address), across reconnects and restarts. If that port is taken, which only happens when another client of the same panel runs on the same host, the integration reports the conflict and retries; it doesn't move to another port.

The **Panel Info** sensor shows `local_port` (the port in use; empty while disconnected), `expected_local_port`, `bind_failures` and `reconnect_attempts`. `timeouts` and `stale_replies_dropped` that keep rising on an otherwise healthy network mean another local client is polling the panel.

## Diagnosing unavailability

There are two places to look:

- **Panel Info sensor attributes.** These are live and stay visible while the panel is offline. To avoid writing a new state every 5 seconds, they hold only values that change when something goes wrong.
- **Diagnostics download** (**Settings → Devices & Services → Orisec → ⋮ → Download diagnostics**). This adds everything that changes on every poll, plus a history of the last 30 connection events. The PIN is redacted and request contents are never included.

| Field | Where | Meaning |
|-------|-------|---------|
| `status` | both | `connected`; `degraded` (polls failing, last known state shown); `reconnecting`; `disconnected` |
| `state_confirmed` / `state_cached_since` | both | Whether entity state comes from the latest poll, or from the panel's last reply at `state_cached_since` |
| `local_endpoint` / `remote_endpoint` | both | The UDP source `ip:port` Home Assistant actually sends from, and the panel address |
| `last_unavailable_at` / `last_unavailable_reason` | both | When and why entities last went unavailable |
| `last_reconnect_at` / `last_reconnect_reason` | both | When the latest reconnect attempt ran, and why: the outage for the first attempt, the previous attempt's failure for later ones |
| `timeouts`, `consecutive_timeouts`, `retries`, `failed_requests` | both | Attempts with no usable reply, attempts in a row without one, resends, and requests that failed after all attempts |
| `stale_replies_dropped`, `corrupt_replies_dropped` | both | Replies rejected because they answered no request in flight, or failed the length/CRC check |
| `refused`, `udp_errors`, `bind_failures`, `session_errors` | both | ICMP refusals, other network errors on send, local port conflicts, and error replies where status was expected |
| `timestamps.last_poll_started` | download | The coordinator last asked for data |
| `timestamps.last_request_sent` | download | A datagram last went out |
| `timestamps.last_reply_received` | download | A usable reply last came back (last successful communication) |
| `timestamps.last_confirmed_state` | download | The panel's status was last read and applied (last successful panel response) |
| `counters.requests`, `packets_sent`, `replies_received`, `polls` | download | Traffic totals since HA started |
| `last_response_time_ms` | download | How long the panel took to answer the last request |
| `history` | download | Timeline of `unavailable`, `state_unconfirmed`, `state_confirmed`, `reconnect_failed` and `reconnected` events |

Reasons start with a category that says where the problem is:

| Category | Meaning |
|----------|---------|
| `no_response` | Requests went out but no usable reply came back: lost packets, the panel ignoring us, or another local client taking our replies |
| `refused` | The panel's IP module answered "port unreachable" |
| `udp_error` | The HA host couldn't send, e.g. no route to the panel |
| `port_in_use` | Another socket on the HA host holds the integration's UDP port, so nothing was sent |
| `session_error` | The panel answered with an error instead of status, e.g. its login session was lost |
| `login_rejected` | The panel refused the PIN |
| `invalid_reply` | The panel answered without the requested status data |
| `socket_error` | A socket-level failure on the HA host |

To see which part has stopped, compare the timestamps in a download:

- `last_poll_started` is old: the coordinator has stopped polling.
- `last_request_sent` is old, but polls are recent: requests aren't being sent (look at `status` and `last_reconnect_reason`).
- Requests are recent but `last_reply_received` is old: replies are missing.
- Replies are recent but `last_confirmed_state` is old: replies are being rejected. Look at `stale_replies_dropped`, `corrupt_replies_dropped` and `session_errors`.

### Debug logging

```yaml
logger:
  logs:
    custom_components.orisec: debug
```

Messages that would repeat on every poll or packet are rate-limited: each kind (successful exchanges, timeouts, stale or corrupt replies, UDP errors, failed polls) is logged at most once a minute, and the next one says how many were skipped. That includes a periodic line showing that requests are being answered, with running totals. Going unavailable, reconnect attempts and reconnections are always logged. Debug logs show command IDs, never request contents, so the PIN and keypad presses are never written.

## Troubleshooting

| Problem | Solution |
|---------|----------|
| "Cannot connect" at startup | Integration retries automatically. Check panel IP is reachable (`ping`) and port 20202 is not firewalled. Only the very first setup needs the panel; after that HA starts from the cached configuration. |
| "Invalid password" | Use the same PIN as your ControlPlus2 mobile app. |
| Entities show unavailable | The panel hasn't answered for 30 seconds, or rejected the session (e.g. it rebooted). The integration auto-reconnects in the background with backoff. If it only happens while the ControlPlus2 app is open in local mode, switch the app to cloud mode or close it when you're not using it. |
| Connection seems flaky | See [Diagnosing unavailability](#diagnosing-unavailability). In short, check the attributes on the **Panel Info** sensor: rising `timeouts`/`retries` point to packet loss on the network, `stale_replies_dropped` to slow replies, `corrupt_replies_dropped` to damaged packets, `refused` to the panel's network module not listening (e.g. while it restarts), and `bind_failures` to another program holding HA's local UDP port. Timeouts and stale replies that rise only while the ControlPlus2 app is open in local mode come from the app competing for the panel's replies (see [Sharing the panel with the ControlPlus2 app](#sharing-the-panel-with-the-controlplus2-app)). `reconnect_attempts` counts the attempts in the current outage, and `last_unavailable_reason` says why entities last went unavailable. Enable debug logging for `custom_components.orisec` for detail. |
| "The alarm panel did not acknowledge the command" | The command was sent once but no reply came back, so it may or may not have been applied. Check the alarm state before trying again. |
| "The alarm panel rejected the command (error …)" | The panel answered with an error, so nothing changed. Error 4 means no one was logged in even after Home Assistant logged in again; error 5 means the panel doesn't support the command. |
| New zones/outputs not appearing | Entities are built from the cached configuration at startup. The cache refreshes once the panel connects; reload the integration to pick up added zones or outputs. |
| "Refused the connection from local port …" / "The panel refused the connection" | The panel's network module answered "port unreachable" and is refusing every client, not just Home Assistant. What triggers it isn't known. It can clear by itself within a few minutes, but has also lasted over half an hour; Home Assistant can't clear it. Restart the IP module by unplugging its network cable for 30 seconds, then reload the integration to reconnect straight away instead of waiting for its back-off. |
| "Local UDP port … is already in use" | Another socket on the HA host holds the port this integration uses for the panel, usually a second Home Assistant (e.g. a test instance with host networking) or a duplicate entry for the same panel. Stop the other one; the integration retries and connects once the port is free. |
| Zones missing | Only zones with a name and type ≠ "Not Used" create entities. |
| Part Set buttons missing | Your panel may not have part-arm modes configured. Check `part_arm_mask` attribute on the alarm entity. |
| Arm command ignored | Your user PIN may not have access to that area. Check `user_area` in panel diagnostics. |
| Remote outputs not visible | Switches are disabled by default. Enable them in **Settings → Devices & Services → Entities**. |
| Card shows "Away/Home" labels | Use `custom:orisec-alarm-panel-card` instead of the built-in `alarm-panel` card. |
| Keypad LCD is blank | LCD only updates while the keypad card/panel is visible. Open the sidebar panel or add the keypad card to a dashboard. |
| Sidebar item missing | Reload the integration or restart HA. The "Orisec" sidebar item registers on first setup. |

## Documentation

- [Protocol Reference](docs/PROTOCOL.md) — Complete binary protocol documentation
- [Design Document](docs/DESIGN.md) — Integration architecture and entity model

## License

MIT
