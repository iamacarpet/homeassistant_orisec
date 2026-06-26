/**
 * Orisec Panel — sidebar page
 *
 * Full-page custom element loaded by HA's panel_custom system.
 * Combines alarm status with the virtual keypad in a single view.
 * Receives `hass` and `panel` properties from HA's frontend framework.
 */

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

  /* Alarm status section */
  .alarm-section {
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

  /* Keypad section */
  .keypad-section {
    background: var(--card-background-color, #fff);
    border-radius: 12px;
    padding: 16px;
    box-shadow: var(--ha-card-box-shadow, 0 2px 6px rgba(0,0,0,0.1));
  }

  .lcd {
    background: #001832;
    color: #a0e8a0;
    font-family: "Courier New", "Lucida Console", monospace;
    font-size: 15px;
    line-height: 1.55;
    padding: 10px 14px;
    margin-bottom: 12px;
    border-radius: 8px;
    border: 2px solid #003060;
    min-height: 96px;
    white-space: pre;
    letter-spacing: 0.5px;
    box-shadow: inset 0 0 20px rgba(0,24,50,0.6);
  }
  .lcd .line { display: block; min-height: 1.55em; }

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
    this._unsubscribe = null;
    this._lcdLines = ["", "", "", ""];
    this._entryId = null;
    this._alarmEntity = null;
    this._rendered = false;
  }

  set hass(hass) {
    const firstSet = !this._hass;
    this._hass = hass;
    if (firstSet) {
      this._findAlarmEntity();
      this._render();
      this._subscribe();
    } else {
      this._updateAlarmStatus();
    }
  }

  set panel(panel) {
    this._panel = panel;
  }

  connectedCallback() {
    if (this._hass && !this._unsubscribe) this._subscribe();
  }

  disconnectedCallback() {
    if (this._unsubscribe) {
      this._unsubscribe();
      this._unsubscribe = null;
    }
  }

  _findAlarmEntity() {
    if (!this._hass) return;
    const entities = Object.keys(this._hass.states).filter(
      (e) => e.startsWith("alarm_control_panel.") &&
        this._hass.states[e].attributes.home_mode !== undefined
    );
    if (entities.length > 0) {
      this._alarmEntity = entities[0];
    } else {
      const all = Object.keys(this._hass.states).filter(
        (e) => e.startsWith("alarm_control_panel.")
      );
      if (all.length > 0) this._alarmEntity = all[0];
    }
  }

  async _subscribe() {
    if (!this._hass || this._unsubscribe) return;

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

      const msg = { type: "orisec/keypad/subscribe" };
      if (this._entryId) msg.entry_id = this._entryId;

      this._unsubscribe = await this._hass.connection.subscribeMessage(
        (event) => this._handleLcdUpdate(event),
        msg,
      );
      this._setStatus("Connected");
    } catch (err) {
      this._setStatus("Connection failed: " + (err.message || err), true);
    }
  }

  _handleLcdUpdate(event) {
    this._lcdLines = event.lines || ["", "", "", ""];
    this._updateLcd();
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
    if (!this._hass || !this._alarmEntity) return;
    this._hass.callService("alarm_control_panel", service, {
      entity_id: this._alarmEntity,
    });
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
        <div class="alarm-section">
          <div class="alarm-status">
            <div class="alarm-badge" id="alarm-badge">
              <ha-icon id="alarm-icon" icon="mdi:shield-off"></ha-icon>
            </div>
            <div class="alarm-info">
              <div class="alarm-state" id="alarm-state">Loading...</div>
              <div class="alarm-detail" id="alarm-detail"></div>
            </div>
          </div>
          <div class="arm-buttons" id="arm-buttons"></div>
        </div>
        <div class="keypad-section">
          <div class="lcd">${
            [0,1,2,3].map(i => `<span class="line line-${i}"></span>`).join("")
          }</div>
          <div class="keypad">${buttonsHtml}</div>
          <div class="panel-status" id="panel-status"></div>
        </div>
      </div>`;

    this.shadowRoot.querySelector(".keypad").addEventListener("click", (e) => {
      const btn = e.target.closest(".key");
      if (!btn) return;
      const idx = parseInt(btn.dataset.idx, 10);
      const def = KEYPAD_BUTTONS[idx];
      if (def && def.char) this._sendKey(def.char);
    });

    this.shadowRoot.getElementById("arm-buttons").addEventListener("click", (e) => {
      const btn = e.target.closest(".arm-btn");
      if (!btn) return;
      this._callAlarmService(btn.dataset.svc);
    });

    this._rendered = true;
    this._updateAlarmStatus();
  }

  _updateAlarmStatus() {
    if (!this._rendered || !this._hass || !this._alarmEntity) return;
    const stateObj = this._hass.states[this._alarmEntity];
    if (!stateObj) return;

    const state = stateObj.state;
    const info = STATE_INFO[state] || { label: state, color: "#9e9e9e", icon: "mdi:shield" };
    const attrs = stateObj.attributes;

    const badge = this.shadowRoot.getElementById("alarm-badge");
    badge.style.background = info.color;
    badge.className = "alarm-badge" + (["arming","pending","triggered"].includes(state) ? " blink" : "");

    const icon = this.shadowRoot.getElementById("alarm-icon");
    icon.setAttribute("icon", info.icon);

    let label = info.label;
    if (state === "armed_home" && attrs.home_mode) label = `Set \u2013 ${attrs.home_mode}`;
    if (state === "armed_night" && attrs.night_mode) label = `Set \u2013 ${attrs.night_mode}`;
    if (state === "armed_vacation" && attrs.vacation_mode) label = `Set \u2013 ${attrs.vacation_mode}`;
    this.shadowRoot.getElementById("alarm-state").textContent = label;

    const details = [];
    if (attrs.ready !== undefined) details.push(attrs.ready ? "Ready" : "Not Ready");
    if (attrs.trouble) details.push("Trouble");
    if (attrs.bypass) details.push("Bypass");
    this.shadowRoot.getElementById("alarm-detail").textContent = details.join(" \u2022 ");

    const isArmed = ["armed_away","armed_home","armed_night","armed_vacation","triggered","pending"].includes(state);
    const isTransitioning = state === "arming" || state === "pending";
    const features = attrs.supported_features || 0;

    let btns = "";
    if (isArmed && !isTransitioning) {
      btns = `<button class="arm-btn disarm" data-svc="alarm_disarm">Disarm</button>`;
    }
    if (!isArmed) {
      if (features & 2) btns += `<button class="arm-btn arm" data-svc="alarm_arm_away">Full Set</button>`;
      if (features & 1) btns += `<button class="arm-btn arm" data-svc="alarm_arm_home">${attrs.home_mode || "Part 1"}</button>`;
      if (features & 4) btns += `<button class="arm-btn arm" data-svc="alarm_arm_night">${attrs.night_mode || "Part 2"}</button>`;
      if (features & 8) btns += `<button class="arm-btn arm" data-svc="alarm_arm_vacation">${attrs.vacation_mode || "Part 3"}</button>`;
    }
    this.shadowRoot.getElementById("arm-buttons").innerHTML = btns;
  }

  _updateLcd() {
    if (!this._rendered) return;
    const lcd = this.shadowRoot.querySelector(".lcd");
    if (!lcd) return;
    for (let i = 0; i < 4; i++) {
      const el = lcd.querySelector(`.line-${i}`);
      if (el) el.textContent = this._lcdLines[i] || "";
    }
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
