const KEYPAD_BUTTONS = [
  { label: "1",      char: "1", cls: "num"    },
  { label: "2",      char: "2", cls: "num"    },
  { label: "3",      char: "3", cls: "num"    },
  { label: "Fire",   char: "F", cls: "danger" },
  { label: "4",      char: "4", cls: "num"    },
  { label: "5",      char: "5", cls: "num"    },
  { label: "6",      char: "6", cls: "num"    },
  { label: "PA",     char: "P", cls: "danger" },
  { label: "7",      char: "7", cls: "num"    },
  { label: "8",      char: "8", cls: "num"    },
  { label: "9",      char: "9", cls: "num"    },
  { label: "Accept", char: "A", cls: "action" },
  { label: "Yes",    char: "Y", cls: "action" },
  { label: "0",      char: "0", cls: "num"    },
  { label: "No",     char: "N", cls: "action" },
  { label: "Omit",   char: "O", cls: "action" },
  { label: "",       char: "",  cls: "blank"  },
  { label: "",       char: "",  cls: "blank"  },
  { label: "Clear",  char: "C", cls: "action" },
  { label: "Reset",  char: "R", cls: "danger" },
  { label: "\u25C0", char: "l", cls: "nav"    },
  { label: "\u25B2", char: "u", cls: "nav"    },
  { label: "\u25BC", char: "d", cls: "nav"    },
  { label: "\u25B6", char: "r", cls: "nav"    },
];

const STATE_INFO = {
  disarmed:       { label: "Disarmed",       color: "#43a047", icon: "mdi:shield-off"      },
  armed_away:     { label: "Full Set",       color: "#fb8c00", icon: "mdi:shield-lock"     },
  armed_home:     { label: "Part Set 1",     color: "#fb8c00", icon: "mdi:shield-home"     },
  armed_night:    { label: "Part Set 2",     color: "#fb8c00", icon: "mdi:shield-moon"     },
  armed_vacation: { label: "Part Set 3",     color: "#fb8c00", icon: "mdi:shield-airplane" },
  arming:         { label: "Setting\u2026",  color: "#fb8c00", icon: "mdi:shield-sync"     },
  pending:        { label: "Entry\u2026",    color: "#fb8c00", icon: "mdi:shield-alert"    },
  triggered:      { label: "ALARM!",         color: "#e53935", icon: "mdi:bell-ring"       },
};

const ICON_MAP = {
  127: "\u25C0", 128: "E", 155: ":", 156: ".",
  159: "\u2612", 160: "\u2610", 163: "\u25B2", 164: "\u25BC",
  165: "\u25B6", 166: "\u25C0", 170: "\u2731", 172: "\u25BC", 173: "\u25B2",
};

// Display is 128 units wide. Character widths per font size index:
const FONT_MULTIPLIER = [7.0, 4.5, 4.5, 4.9];
// Map font size index to pixel font size for canvas rendering:
const FONT_SIZES = [20, 20, 20, 14];

const LCD_WIDTH = 380;
const LCD_HEIGHT = 112;
const LCD_LINE_H = 28;
const LCD_BG = "#001832";
const LCD_FG = "#e0e0e0";
const LCD_INV_BG = "#e0e0e0";
const LCD_INV_FG = "#102040";
const LCD_UNITS = 128;

function lcdFont(size, bold) {
  return (bold ? "bold " : "") + size + "px 'Courier New', 'Lucida Console', monospace";
}

function renderLcd(canvas, raw, time) {
  const ctx = canvas.getContext("2d");
  const dpr = window.devicePixelRatio || 1;
  canvas.width = LCD_WIDTH * dpr;
  canvas.height = LCD_HEIGHT * dpr;
  canvas.style.width = LCD_WIDTH + "px";
  canvas.style.height = LCD_HEIGHT + "px";
  ctx.scale(dpr, dpr);

  ctx.fillStyle = LCD_BG;
  ctx.fillRect(0, 0, LCD_WIDTH, LCD_HEIGHT);

  if (!raw || raw.length === 0) return;

  // Parse raw bytes into line segment arrays
  // Each segment: { ch, inv, fontSize } or { progress, value, max }
  const lines = [[], [], [], []];
  const lineAligns = ["left", "left", "left", "left"];
  const linePadX = [null, null, null, null]; // explicit X position from byte 8
  let cur = -1;
  let inverted = false;
  let fontSize = 0;

  let i = 0;
  while (i < raw.length) {
    const b = raw[i];
    if (b === 17) {
      cur = cur === -1 ? 0 : Math.min(cur + 1, 3);
      lines[cur] = [];
      lineAligns[cur] = "left";
      linePadX[cur] = null;
      inverted = false;
      fontSize = 0;
    } else if (b >= 18 && b <= 21) {
      cur = b - 18;
      lines[cur] = [];
      lineAligns[cur] = "left";
      linePadX[cur] = null;
      inverted = false;
      fontSize = 0;
    } else if (b === 5) {
      inverted = false;
    } else if (b === 6) {
      inverted = true;
    } else if (b === 8 && i + 1 < raw.length) {
      // Pad right: position X at (padRight / 128) * width
      i++;
      if (cur >= 0) linePadX[cur] = raw[i];
    } else if (b === 9) {
      // Reset X to origin
      if (cur >= 0) linePadX[cur] = 0;
    } else if (b === 10 && cur >= 0) {
      lineAligns[cur] = "center";
    } else if (b === 11 && cur >= 0) {
      lineAligns[cur] = "right";
    } else if (b === 12 && cur >= 0) {
      const ts = (time[0] < 10 ? "0" : "") + time[0] + ":" +
                 (time[1] < 10 ? "0" : "") + time[1] + "." +
                 (time[2] < 10 ? "0" : "") + time[2];
      for (let c = 0; c < ts.length; c++) {
        lines[cur].push({ ch: ts[c], inv: inverted, fs: fontSize });
      }
    } else if (b === 14) {
      // Progress bar: 3 param bytes (width, max, current)
      if (cur >= 0 && i + 3 < raw.length) {
        lines[cur].push({
          progress: true,
          value: raw[i + 3],
          max: raw[i + 2] || 1,
          barWidth: raw[i + 1],
        });
      }
      i += 3;
    } else if (b === 7 || b === 16) {
      i++; // skip 1 param byte
    } else if (b === 26) {
      i++; // skip 1 param byte (icon flag)
    } else if (b >= 22 && b <= 25) {
      fontSize = b - 22;
    } else if (b >= 32 && b <= 125 && cur >= 0) {
      lines[cur].push({ ch: String.fromCharCode(b), inv: inverted, fs: fontSize });
    } else if (b > 126 && b <= 173 && cur >= 0) {
      const icon = ICON_MAP[b];
      if (icon) lines[cur].push({ ch: icon, inv: inverted, fs: fontSize, isIcon: true });
    }
    i++;
  }

  // Render each line
  const pxPerUnit = LCD_WIDTH / LCD_UNITS;

  for (let line = 0; line < 4; line++) {
    const segments = lines[line];
    if (!segments || segments.length === 0) continue;

    const y = line * LCD_LINE_H + LCD_LINE_H / 2;
    const hasProgress = segments.find(s => s.progress);

    if (hasProgress) {
      const s = hasProgress;
      const barW = (s.barWidth || 100) * pxPerUnit;
      const barH = 10;
      const barX = (LCD_WIDTH - barW) / 2;
      const barY = y - barH / 2;
      ctx.strokeStyle = LCD_FG;
      ctx.lineWidth = 1;
      ctx.strokeRect(barX, barY, barW, barH);
      const fill = Math.min(s.value / (s.max || 1), 1) * barW;
      ctx.fillStyle = LCD_FG;
      ctx.fillRect(barX, barY, fill, barH);
      continue;
    }

    // Calculate total width in display units
    let totalUnits = 0;
    for (const seg of segments) {
      totalUnits += FONT_MULTIPLIER[seg.fs || 0];
    }

    // Determine starting X position in pixels
    let startX;
    if (linePadX[line] !== null) {
      startX = linePadX[line] * pxPerUnit;
    } else if (lineAligns[line] === "center") {
      startX = (LCD_WIDTH - totalUnits * pxPerUnit) / 2;
    } else if (lineAligns[line] === "right") {
      startX = LCD_WIDTH - totalUnits * pxPerUnit - 4 * pxPerUnit;
    } else {
      startX = 2 * pxPerUnit;
    }

    // Draw segments character by character
    let xPos = startX;
    ctx.textBaseline = "middle";

    for (const seg of segments) {
      const fs = seg.fs || 0;
      const charW = FONT_MULTIPLIER[fs] * pxPerUnit;
      const pxSize = FONT_SIZES[fs];
      const font = lcdFont(pxSize, seg.inv);

      ctx.font = font;

      if (seg.inv) {
        ctx.fillStyle = LCD_INV_BG;
        ctx.fillRect(xPos, y - LCD_LINE_H / 2 + 2, charW, LCD_LINE_H - 4);
        ctx.fillStyle = LCD_INV_FG;
      } else {
        ctx.fillStyle = LCD_FG;
      }

      // Center character within its cell
      const measured = ctx.measureText(seg.ch).width;
      const charX = xPos + (charW - measured) / 2;
      ctx.fillText(seg.ch, charX, y);

      xPos += charW;
    }
  }
}

const PANEL_STYLES = `
  :host {
    display: block;
    height: 100%;
    background: var(--primary-background-color);
  }

  .toolbar {
    display: flex;
    align-items: center;
    height: 56px;
    padding: 0 16px;
    background: var(--app-header-background-color, var(--primary-color));
    color: var(--app-header-text-color, #fff);
    font-size: 20px;
    font-weight: 400;
  }
  .toolbar ha-icon {
    --mdc-icon-size: 24px;
    margin-right: 12px;
  }

  .content {
    max-width: 480px;
    margin: 0 auto;
    padding: 16px;
  }

  .section {
    background: var(--card-background-color, #fff);
    border-radius: 12px;
    padding: 20px;
    margin-bottom: 16px;
    box-shadow: var(--ha-card-box-shadow, 0 2px 6px rgba(0,0,0,0.1));
  }

  .alarm-status {
    display: flex;
    align-items: center;
    gap: 16px;
    margin-bottom: 16px;
  }

  .alarm-badge {
    width: 56px;
    height: 56px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
  }
  .alarm-badge ha-icon { --mdc-icon-size: 28px; color: #fff; }
  .alarm-badge.blink { animation: pulse 1.4s ease-in-out infinite; }
  @keyframes pulse { 0%,100% { opacity:1 } 50% { opacity:0.4 } }

  .alarm-info { flex: 1; }
  .alarm-state { font-size: 1.3rem; font-weight: 500; color: var(--primary-text-color); }
  .alarm-detail { font-size: 0.85rem; color: var(--secondary-text-color); margin-top: 2px; }

  .system-indicators {
    display: flex;
    gap: 16px;
    margin-bottom: 16px;
    font-size: 0.85rem;
    color: var(--secondary-text-color);
  }
  .indicator { display: flex; align-items: center; gap: 4px; }
  .indicator .dot {
    width: 8px; height: 8px; border-radius: 50%;
  }
  .dot.ok { background: #43a047; }
  .dot.warn { background: #fb8c00; }
  .dot.error { background: #e53935; }

  .arm-buttons {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
  }
  .arm-btn {
    flex: 1;
    min-width: 80px;
    padding: 10px 12px;
    border: none;
    border-radius: 8px;
    cursor: pointer;
    font-size: 0.85rem;
    font-weight: 500;
    font-family: inherit;
    transition: filter 0.15s;
  }
  .arm-btn:hover { filter: brightness(1.1); }
  .arm-btn:active { filter: brightness(0.9); }
  .arm-btn.arm { background: var(--primary-color); color: var(--text-primary-color, #fff); }
  .arm-btn.disarm { background: var(--error-color, #e53935); color: #fff; }

  .section-header {
    font-size: 0.875rem;
    font-weight: 500;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    color: var(--secondary-text-color);
    margin-bottom: 12px;
  }

  .event-log {
    max-height: 160px;
    overflow-y: auto;
  }
  .event-item {
    display: flex;
    gap: 8px;
    padding: 4px 0;
    font-size: 0.85rem;
    border-bottom: 1px solid var(--divider-color, #e8e8e8);
  }
  .event-item:last-child { border-bottom: none; }
  .event-time {
    color: var(--secondary-text-color);
    font-family: monospace;
    flex-shrink: 0;
  }
  .event-text { color: var(--primary-text-color); }
  .event-text.alarm { color: var(--error-color, #e53935); font-weight: 600; }
  .event-text.cleared { color: #43a047; }
  .no-events { color: var(--secondary-text-color); font-size: 0.85rem; font-style: italic; }

  .lcd-container {
    position: relative;
    margin-bottom: 12px;
    height: 116px;
    max-width: 384px;
    margin-left: auto;
    margin-right: auto;
  }
  .lcd-canvas {
    display: block;
    width: 100%;
    height: 100%;
    border-radius: 8px;
    border: 2px solid #003060;
    box-shadow: inset 0 0 20px rgba(0,24,50,0.6);
    background: ${LCD_BG};
  }
  .lcd-overlay {
    position: absolute;
    top: 0; left: 0; right: 0; bottom: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    background: ${LCD_BG};
    border-radius: 8px;
    border: 2px solid #003060;
    cursor: pointer;
    transition: filter 0.15s;
  }
  .lcd-overlay:hover { filter: brightness(1.1); }
  .lcd-overlay-text {
    color: #a0e8a0;
    font-family: "Courier New", monospace;
    font-size: 16px;
    text-align: center;
  }
  .lcd-loading {
    position: absolute;
    top: 0; left: 0; right: 0; bottom: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    background: ${LCD_BG};
    border-radius: 8px;
    border: 2px solid #003060;
  }
  .lcd-loading-text {
    color: #a0e8a0;
    font-family: "Courier New", monospace;
    font-size: 16px;
    animation: blink-text 1.2s ease-in-out infinite;
  }
  @keyframes blink-text { 0%,100% { opacity:1 } 50% { opacity:0.3 } }

  .keypad-controls {
    display: flex;
    justify-content: center;
    margin-bottom: 12px;
  }
  .disconnect-btn {
    padding: 6px 16px;
    border: 1px solid var(--divider-color, #e0e0e0);
    border-radius: 6px;
    background: var(--card-background-color, #fff);
    color: var(--secondary-text-color);
    font-size: 0.8rem;
    cursor: pointer;
    font-family: inherit;
  }
  .disconnect-btn:hover { background: var(--secondary-background-color, #f5f5f5); }

  .keypad {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 6px;
  }

  .key {
    padding: 14px 4px;
    border: 1px solid var(--divider-color, #e0e0e0);
    border-radius: 8px;
    font-size: 14px;
    font-weight: 500;
    cursor: pointer;
    text-align: center;
    background: var(--card-background-color, #fff);
    color: var(--primary-text-color);
    font-family: inherit;
    transition: filter 0.1s, transform 0.08s;
    user-select: none;
    -webkit-tap-highlight-color: transparent;
  }
  .key:hover  { filter: brightness(0.95); }
  .key:active { filter: brightness(0.85); transform: scale(0.96); }
  .key.num    { font-size: 20px; font-weight: 600; }
  .key.danger { background: var(--error-color, #e53935); color: #fff; border-color: var(--error-color, #e53935); }
  .key.action { background: var(--primary-color); color: var(--text-primary-color, #fff); border-color: var(--primary-color); }
  .key.nav    { background: var(--secondary-background-color, #f5f5f5); font-size: 18px; }
  .key.blank  { visibility: hidden; pointer-events: none; }
  .key.flash  { filter: brightness(1.3); }

  .panel-status {
    text-align: center;
    padding: 8px;
    font-size: 0.8rem;
    color: var(--secondary-text-color);
  }
  .panel-status.error { color: var(--error-color, #e53935); }
`;

class OrisecPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._panel = null;
    this._panelUnsub = null;
    this._keypadUnsub = null;
    this._entryId = null;
    this._rendered = false;
    this._panelState = null;
    this._keypadConnected = false;
    this._keypadLoading = false;
    this._lcdRaw = null;
    this._lcdTime = [0, 0, 0];
  }

  set hass(hass) {
    const firstSet = !this._hass;
    this._hass = hass;
    if (firstSet) {
      this._render();
      this._subscribePanelState();
    }
  }

  set panel(panel) {
    this._panel = panel;
  }

  connectedCallback() {
    if (this._hass && !this._panelUnsub) this._subscribePanelState();
  }

  disconnectedCallback() {
    this._teardownPanel();
    this._teardownKeypad();
  }

  _teardownPanel() {
    if (this._panelUnsub) {
      this._panelUnsub();
      this._panelUnsub = null;
    }
  }

  _teardownKeypad() {
    if (this._keypadUnsub) {
      this._keypadUnsub();
      this._keypadUnsub = null;
    }
    this._keypadConnected = false;
    this._keypadLoading = false;
    this._lcdRaw = null;
  }

  async _subscribePanelState() {
    if (!this._hass || this._panelUnsub) return;
    try {
      const entries = await this._hass.connection.sendMessagePromise({
        type: "orisec/keypad/entries",
      });
      if (entries && entries.length > 0) {
        this._entryId = entries[0].entry_id;
      } else {
        this._setStatus("No Orisec panel found", true);
        return;
      }

      const msg = { type: "orisec/panel/subscribe" };
      if (this._entryId) msg.entry_id = this._entryId;

      this._panelUnsub = await this._hass.connection.subscribeMessage(
        (event) => this._handlePanelUpdate(event),
        msg,
      );
    } catch (err) {
      this._setStatus("Connection failed: " + (err.message || err), true);
    }
  }

  _handlePanelUpdate(state) {
    this._panelState = state;
    this._updateAlarmSection();
    this._updateEventLog();
  }

  async _connectKeypad() {
    if (!this._hass || this._keypadUnsub) return;
    this._keypadLoading = true;
    this._updateKeypadView();

    try {
      const msg = { type: "orisec/keypad/subscribe" };
      if (this._entryId) msg.entry_id = this._entryId;

      this._keypadUnsub = await this._hass.connection.subscribeMessage(
        (event) => this._handleLcdUpdate(event),
        msg,
      );
      this._keypadConnected = true;
      this._updateKeypadView();
    } catch (err) {
      this._keypadLoading = false;
      this._keypadConnected = false;
      this._updateKeypadView();
      this._setStatus("Keypad connection failed: " + (err.message || err), true);
    }
  }

  _disconnectKeypad() {
    this._teardownKeypad();
    this._updateKeypadView();
  }

  _handleLcdUpdate(event) {
    this._lcdRaw = event.lcd_raw || [];
    this._lcdTime = event.time || [0, 0, 0];
    this._keypadLoading = false;
    this._updateKeypadView();
    this._renderLcd();
  }

  async _sendKey(char) {
    if (!this._hass || !char.trim()) return;
    try {
      const msg = { type: "orisec/keypad/press", char };
      if (this._entryId) msg.entry_id = this._entryId;
      await this._hass.connection.sendMessagePromise(msg);
    } catch (err) {
      this._setStatus("Send failed: " + (err.message || err), true);
    }
  }

  _callAlarmService(service) {
    if (!this._hass || !this._panelState) return;
    const entities = Object.keys(this._hass.states).filter(
      e => e.startsWith("alarm_control_panel.") &&
        this._hass.states[e].attributes.home_mode !== undefined
    );
    let entity = entities[0];
    if (!entity) {
      const all = Object.keys(this._hass.states).filter(
        e => e.startsWith("alarm_control_panel.")
      );
      entity = all[0];
    }
    if (!entity) return;
    this._hass.callService("alarm_control_panel", service, { entity_id: entity });
  }

  _render() {
    const buttonsHtml = KEYPAD_BUTTONS.map((btn, i) =>
      `<button class="key ${btn.cls}" data-idx="${i}">${btn.label}</button>`
    ).join("");

    this.shadowRoot.innerHTML = `
      <style>${PANEL_STYLES}</style>
      <div class="toolbar">
        <ha-icon icon="mdi:shield-home"></ha-icon>
        <span>Orisec</span>
      </div>
      <div class="content">
        <div class="section" id="alarm-section">
          <div class="alarm-status">
            <div class="alarm-badge" id="alarm-badge">
              <ha-icon id="alarm-icon" icon="mdi:shield-off"></ha-icon>
            </div>
            <div class="alarm-info">
              <div class="alarm-state" id="alarm-state">Connecting...</div>
              <div class="alarm-detail" id="alarm-detail"></div>
            </div>
          </div>
          <div class="system-indicators" id="system-indicators"></div>
          <div class="arm-buttons" id="arm-buttons"></div>
        </div>

        <div class="section" id="events-section">
          <div class="section-header">Recent Events</div>
          <div class="event-log" id="event-log">
            <div class="no-events">No events recorded</div>
          </div>
        </div>

        <div class="section" id="keypad-section">
          <div class="section-header">Keypad</div>
          <div class="lcd-container" id="lcd-container">
            <canvas class="lcd-canvas" id="lcd-canvas"></canvas>
            <div class="lcd-overlay" id="lcd-overlay">
              <div class="lcd-overlay-text">Click to connect keypad</div>
            </div>
          </div>
          <div class="keypad-controls" id="keypad-controls" style="display:none">
            <button class="disconnect-btn" id="disconnect-btn">Disconnect</button>
          </div>
          <div class="keypad" id="keypad-grid" style="display:none">${buttonsHtml}</div>
          <div class="panel-status" id="panel-status"></div>
        </div>
      </div>`;

    this.shadowRoot.getElementById("lcd-overlay").addEventListener("click", () => {
      this._connectKeypad();
    });

    this.shadowRoot.getElementById("disconnect-btn").addEventListener("click", () => {
      this._disconnectKeypad();
    });

    this.shadowRoot.getElementById("keypad-grid").addEventListener("click", (e) => {
      const btn = e.target.closest(".key");
      if (!btn) return;
      const idx = parseInt(btn.dataset.idx, 10);
      const def = KEYPAD_BUTTONS[idx];
      if (def && def.char) {
        this._sendKey(def.char);
        btn.classList.add("flash");
        setTimeout(() => btn.classList.remove("flash"), 120);
      }
    });

    this.shadowRoot.getElementById("arm-buttons").addEventListener("click", (e) => {
      const btn = e.target.closest(".arm-btn");
      if (!btn) return;
      this._callAlarmService(btn.dataset.svc);
    });

    this._rendered = true;
  }

  _updateAlarmSection() {
    if (!this._rendered || !this._panelState) return;
    const ps = this._panelState;
    const area = ps.areas && ps.areas[0];
    if (!area) return;

    const state = area.state;
    const info = STATE_INFO[state] || { label: state, color: "#9e9e9e", icon: "mdi:shield" };

    const badge = this.shadowRoot.getElementById("alarm-badge");
    badge.style.background = info.color;
    badge.className = "alarm-badge" + (
      ["arming", "pending", "triggered"].includes(state) ? " blink" : ""
    );

    this.shadowRoot.getElementById("alarm-icon").setAttribute("icon", info.icon);

    let label = info.label;
    const names = ps.part_arm_names || [];
    if (state === "armed_home" && names[0]) label = "Set \u2013 " + names[0];
    if (state === "armed_night" && names[1]) label = "Set \u2013 " + names[1];
    if (state === "armed_vacation" && names[2]) label = "Set \u2013 " + names[2];
    this.shadowRoot.getElementById("alarm-state").textContent = label;

    const details = [];
    if (area.ready !== undefined) details.push(area.ready ? "Ready" : "Not Ready");
    if (area.trouble) details.push("Trouble");
    if (area.bypass) details.push("Bypass");
    this.shadowRoot.getElementById("alarm-detail").textContent = details.join(" \u2022 ");

    let indicators = "";
    const acOk = ps.ac_power;
    const batFault = ps.battery_fault;
    indicators += `<div class="indicator"><span class="dot ${acOk ? "ok" : "error"}"></span>AC${acOk ? "" : " Fault"}</div>`;
    indicators += `<div class="indicator"><span class="dot ${batFault ? "error" : "ok"}"></span>Battery${batFault ? " Fault" : ""}</div>`;
    if (area.trouble) {
      indicators += `<div class="indicator"><span class="dot warn"></span>Trouble</div>`;
    }
    this.shadowRoot.getElementById("system-indicators").innerHTML = indicators;

    const isArmed = ["armed_away", "armed_home", "armed_night", "armed_vacation", "triggered", "pending"].includes(state);
    const isTransitioning = state === "arming" || state === "pending";
    const mask = ps.part_arm_mask || 0;

    let btns = "";
    if (isArmed && !isTransitioning) {
      btns = `<button class="arm-btn disarm" data-svc="alarm_disarm">Disarm</button>`;
    }
    if (!isArmed) {
      btns += `<button class="arm-btn arm" data-svc="alarm_arm_away">Full Set</button>`;
      if (mask & 1) btns += `<button class="arm-btn arm" data-svc="alarm_arm_home">${names[0] || "Part 1"}</button>`;
      if (mask & 2) btns += `<button class="arm-btn arm" data-svc="alarm_arm_night">${names[1] || "Part 2"}</button>`;
      if (mask & 4) btns += `<button class="arm-btn arm" data-svc="alarm_arm_vacation">${names[2] || "Part 3"}</button>`;
    }
    this.shadowRoot.getElementById("arm-buttons").innerHTML = btns;
  }

  _updateEventLog() {
    if (!this._rendered || !this._panelState) return;
    const events = this._panelState.events || [];
    const container = this.shadowRoot.getElementById("event-log");

    if (events.length === 0) {
      container.innerHTML = '<div class="no-events">No events recorded</div>';
      return;
    }

    container.innerHTML = events.slice().reverse().map(ev => {
      const time = ev.timestamp ? ev.timestamp.split("T")[1] || "" : "";
      const shortTime = time.substring(0, 5);
      let text = "";
      let cls = "";
      if (ev.type === "alarm_triggered") {
        text = ev.area_name + " \u2014 ALARM TRIGGERED";
        if (ev.data.fire) text += " (Fire)";
        if (ev.data.pa) text += " (PA)";
        cls = "alarm";
      } else if (ev.type === "alarm_cleared") {
        text = ev.area_name + " \u2014 Alarm Cleared";
        cls = "cleared";
      } else if (ev.type === "state_changed") {
        const oldLabel = (STATE_INFO[ev.data.old_state] || {}).label || ev.data.old_state;
        const newLabel = (STATE_INFO[ev.data.new_state] || {}).label || ev.data.new_state;
        text = ev.area_name + " \u2014 " + oldLabel + " \u2192 " + newLabel;
      }
      return `<div class="event-item"><span class="event-time">${shortTime}</span><span class="event-text ${cls}">${text}</span></div>`;
    }).join("");
  }

  _updateKeypadView() {
    if (!this._rendered) return;
    const overlay = this.shadowRoot.getElementById("lcd-overlay");
    const canvas = this.shadowRoot.getElementById("lcd-canvas");
    const controls = this.shadowRoot.getElementById("keypad-controls");
    const grid = this.shadowRoot.getElementById("keypad-grid");
    const container = this.shadowRoot.getElementById("lcd-container");
    const existingLoading = container.querySelector(".lcd-loading");

    if (!this._keypadConnected && !this._keypadLoading) {
      // Disconnected state: show overlay, hide everything else
      overlay.style.display = "flex";
      canvas.style.visibility = "hidden";
      if (existingLoading) existingLoading.remove();
      controls.style.display = "none";
      grid.style.display = "none";
    } else if (this._keypadLoading && !this._lcdRaw) {
      // Loading state: show loading message
      overlay.style.display = "none";
      canvas.style.visibility = "hidden";
      controls.style.display = "none";
      grid.style.display = "none";
      if (!existingLoading) {
        const loading = document.createElement("div");
        loading.className = "lcd-loading";
        loading.innerHTML = '<div class="lcd-loading-text">Loading, please wait...</div>';
        container.appendChild(loading);
      }
    } else {
      // Connected state: show canvas and keypad
      overlay.style.display = "none";
      canvas.style.visibility = "visible";
      if (existingLoading) existingLoading.remove();
      controls.style.display = "flex";
      grid.style.display = "grid";
    }
  }

  _renderLcd() {
    if (!this._rendered || !this._lcdRaw) return;
    const canvas = this.shadowRoot.getElementById("lcd-canvas");
    if (!canvas) return;
    renderLcd(canvas, this._lcdRaw, this._lcdTime);
  }

  _setStatus(text, isError) {
    if (!this._rendered) return;
    const el = this.shadowRoot.getElementById("panel-status");
    if (!el) return;
    el.textContent = text;
    el.className = isError ? "panel-status error" : "panel-status";
  }
}

customElements.define("orisec-panel", OrisecPanel);
