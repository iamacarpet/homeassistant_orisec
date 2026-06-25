# Orisec ControlPlus2 — Home Assistant Integration

Local LAN integration for Orisec ControlPlus2 alarm panels (CP10, CP20, CP40, CP200, EP100, and Z-variants).

Communicates directly with the panel over UDP on port 20202 — no cloud, no internet dependency, no latency.

## Features

- **Alarm control** — Arm (full/part), disarm, per-area state with triggered/arming/pending detection
- **Part-arm modes** — Separate entities for each part-arm mode (e.g. "Bedtime", "Night") with custom names from the panel
- **Zone sensors** — Binary sensors for every configured zone with proper device classes (motion, door, smoke, moisture, gas, etc.)
- **Tamper detection** — Per-zone tamper sensors (disabled by default)
- **Remote outputs** — Switch entities for all remote outputs
- **Panel diagnostics** — Sensor with panel type, version, AC power, trouble state
- **Alarm events** — Fires `orisec_alarm_triggered` on the HA event bus with area, fire, PA, and bell details
- **Fast polling** — 2-second update interval via lightweight UDP packets

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
- Home Assistant 2024.1+

## Installation

### HACS (Manual Repository)

1. In HACS, go to **Integrations** → three-dot menu → **Custom repositories**
2. Add this repository URL with category **Integration**
3. Search for "Orisec" and install
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

The integration validates your credentials during setup. If the password is rejected, you'll see an error immediately.

## Entities Created

### Alarm Control Panel

| Entity | Description |
|--------|-------------|
| `alarm_control_panel.{area_name}` | Primary alarm entity per area (arm away / arm home / disarm) |
| `alarm_control_panel.{area_name}_{part_arm_name}` | One per part-arm mode (arm home = activate that mode) |

**States:** `disarmed`, `armed_away`, `armed_home`, `arming` (exit timer), `pending` (entry timer), `triggered`

**Attributes:** `ready`, `trouble`, `bypass`, `bell`, `ac_fault`, `battery_fault`, `active_part_arm`

### Binary Sensors

| Entity | Description |
|--------|-------------|
| `binary_sensor.{zone_name}` | Zone state — on when active/open |
| `binary_sensor.{zone_name}_tamper` | Tamper detection (disabled by default) |

Device classes are auto-assigned from zone type: `motion`, `door`, `opening`, `smoke`, `moisture`, `gas`, `safety`, `tamper`, `occupancy`, `problem`.

**Attributes:** `zone_number`, `zone_type`, `raw_status`, `activity_timer`

### Switches

| Entity | Description |
|--------|-------------|
| `switch.{output_name}` | Remote output — toggle on/off |

### Sensors

| Entity | Description |
|--------|-------------|
| `sensor.panel_status` | Online/offline with panel diagnostics |

**Attributes:** `panel_type`, `panel_version`, `serial`, `max_zones`, `max_areas`, `ac_power`, `trouble`, `engineer_required`, `part_arm_*_name`

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
          message: "{{ trigger.event.data.area_name }} alarm triggered!"
          data:
            priority: high
```

### Arm at bedtime

```yaml
automation:
  - alias: "Arm Part 1 at Midnight"
    trigger:
      - platform: time
        at: "00:00:00"
    action:
      - service: alarm_control_panel.alarm_arm_home
        target:
          entity_id: alarm_control_panel.home_bedtime
```

### Zone activity light

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

1. **Login** — Sends password, receives panel info and capabilities
2. **Setup** — Queries zone types, names, area names, output names, part-arm mode names
3. **Poll** — Every 2 seconds, reads system output states (arm/alarm/ready flags), zone status (open/tamper), zone timers, and remote output states
4. **Commands** — Arm/disarm sends keypress codes; output toggle sends control commands

All communication is local UDP with no encryption needed. See [docs/PROTOCOL.md](docs/PROTOCOL.md) for full protocol details.

## Troubleshooting

| Problem | Solution |
|---------|----------|
| "Cannot connect" | Verify panel IP is reachable (`ping`). Check port 20202 is not firewalled. |
| "Invalid password" | Use the same PIN as your ControlPlus2 mobile app. |
| Entities show unavailable | Panel may have rebooted. The integration auto-reconnects on the next poll. |
| Zones missing | Only zones with a name and type ≠ "Not Used" create entities. |
| Arm command doesn't work | Check the user area mask — your password may not have access to that area. |

## Documentation

- [Protocol Reference](docs/PROTOCOL.md) — Complete binary protocol documentation
- [Design Document](docs/DESIGN.md) — Integration architecture and entity model

## License

MIT
