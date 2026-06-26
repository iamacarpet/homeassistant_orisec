# Orisec ControlPlus2 — Home Assistant Integration

Local LAN integration for Orisec ControlPlus2 alarm panels (CP10, CP20, CP40, CP200, EP100, and Z-variants).

Communicates directly with the panel over UDP on port 20202 — no cloud, no internet dependency, no latency.

## Features

- **Alarm control** — Full Set, Part Set (1/2/3), and Disarm per area, with the panel's own arm-mode names
- **Part-arm modes** — Up to 3 part-arm modes (Home/Night/Vacation) driven by the panel's own programmed names
- **Zone sensors** — Binary sensors for every configured zone with auto-assigned device classes
- **System sensors** — AC power, battery fault, tamper, bell active, and trouble indicators
- **Tamper detection** — Per-zone tamper sensors (disabled by default to reduce clutter)
- **Remote outputs** — Switch entities for all remote outputs (disabled by default)
- **Panel diagnostics** — Sensor with panel type, version, serial, and connection state
- **Alarm events** — Fires `orisec_alarm_triggered` / `orisec_alarm_cleared` / `orisec_state_changed` on the HA event bus
- **Fast polling** — 2-second update interval via lightweight UDP packets
- **Auto-reconnect** — If communication fails, the integration reconnects automatically on the next poll
- **Custom Lovelace card** — `orisec-alarm-panel-card` auto-registered; shows your panel's arm-mode names instead of the HA defaults (Away/Home/Night/Vacation)

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

One entity is created per area. It appears in the **Security** section of the HA dashboard automatically.

| Entity | Description |
|--------|-------------|
| `alarm_control_panel.{area_name}` | Alarm control for the area |

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
| `sensor.panel_info` | Online/offline (DIAGNOSTIC) |

**Attributes:** `panel_type`, `panel_version`, `serial`, `host`, `max_zones`, `max_areas`, `max_remote_outputs`, `part_arm_mask`, `ac_power`, `trouble`, `engineer_required`, `area_N_state`, `area_N_name`, `part_arm_names`

## Custom Lovelace Card

The integration auto-registers `orisec-alarm-panel-card` — a Lovelace card that replaces HA's generic "Away / Home / Night / Vacation" button labels with the names programmed into your panel.

Add it to a dashboard with:

```yaml
type: custom:orisec-alarm-panel-card
entity: alarm_control_panel.home
name: My Alarm   # optional
```

The card shows the current state (Disarmed / Full Set / Set – {name} / Setting… / Entry delay… / Alarm!) with a colour-coded badge and blinking animation for active states.

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
          entity_id: alarm_control_panel.home
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
        entity_id: alarm_control_panel.home
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

This performs comprehensive read-only queries and does **not** arm, disarm, or modify any panel state.

## How It Works

The integration communicates with the panel using its native binary UDP protocol:

1. **Login** — Sends password, receives panel info, capabilities, and user area mask
2. **Setup** — Queries zone types, names, area names, output names, part-arm mode names
3. **Poll** — Every 2 seconds: reads system output states (arm/alarm/ready flags), zone status (open/tamper), zone timers, and remote output states in a single multi-query
4. **Commands** — Arm/disarm sends keypress codes; output toggle sends control commands

All communication is local UDP. See [docs/PROTOCOL.md](docs/PROTOCOL.md) for full protocol details.

## Troubleshooting

| Problem | Solution |
|---------|----------|
| "Cannot connect" at startup | Integration retries automatically. Check panel IP is reachable (`ping`) and port 20202 is not firewalled. |
| "Invalid password" | Use the same PIN as your ControlPlus2 mobile app. |
| Entities show unavailable | Panel may have rebooted. The integration auto-reconnects on the next poll cycle. |
| Zones missing | Only zones with a name and type ≠ "Not Used" create entities. |
| Part Set buttons missing | Your panel may not have part-arm modes configured. Check `part_arm_mask` attribute on the alarm entity. |
| Arm command ignored | Your user PIN may not have access to that area. Check `user_area` in panel diagnostics. |
| Remote outputs not visible | Switches are disabled by default. Enable them in **Settings → Devices & Services → Entities**. |
| Card shows "Away/Home" labels | Use `custom:orisec-alarm-panel-card` instead of the built-in `alarm-panel` card. |

## Documentation

- [Protocol Reference](docs/PROTOCOL.md) — Complete binary protocol documentation
- [Design Document](docs/DESIGN.md) — Integration architecture and entity model

## License

MIT
