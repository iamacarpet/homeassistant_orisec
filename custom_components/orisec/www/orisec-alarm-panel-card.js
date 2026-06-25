/**
 * Orisec Alarm Panel Card
 *
 * A Lovelace card that mirrors the built-in alarm-panel card layout but
 * replaces HA's generic "Away / Home / Night / Vacation" labels with the
 * arm-mode names programmed into the panel (surfaced as entity attributes).
 *
 * Usage:
 *   type: custom:orisec-alarm-panel-card
 *   entity: alarm_control_panel.home
 *   name: My Alarm   # optional override
 */

const FEATURE = {
  ARM_HOME:     1,
  ARM_AWAY:     2,
  ARM_NIGHT:    4,
  ARM_VACATION: 8,
};

const STATE_STYLE = {
  disarmed:       { color: "var(--success-color, #43a047)",  icon: "mdi:shield-off",       blink: false },
  armed_away:     { color: "var(--warning-color, #fb8c00)",  icon: "mdi:shield-lock",      blink: false },
  armed_home:     { color: "var(--warning-color, #fb8c00)",  icon: "mdi:shield-home",      blink: false },
  armed_night:    { color: "var(--warning-color, #fb8c00)",  icon: "mdi:shield-moon",      blink: false },
  armed_vacation: { color: "var(--warning-color, #fb8c00)",  icon: "mdi:shield-airplane",  blink: false },
  arming:         { color: "var(--warning-color, #fb8c00)",  icon: "mdi:shield-sync",      blink: true  },
  pending:        { color: "var(--warning-color, #fb8c00)",  icon: "mdi:shield-alert",     blink: true  },
  triggered:      { color: "var(--error-color,   #e53935)",  icon: "mdi:bell-ring",        blink: true  },
};

const STYLES = `
  :host { display: block; }
  ha-card { overflow: hidden; }

  .name {
    padding: 16px 16px 0;
    font-size: 0.875rem;
    font-weight: 500;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    color: var(--secondary-text-color);
  }

  .body {
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 20px 16px 8px;
    gap: 10px;
  }

  .badge {
    width: 72px;
    height: 72px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
  }
  .badge.blink { animation: pulse 1.4s ease-in-out infinite; }
  @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }

  ha-icon { --mdc-icon-size: 34px; color: #fff; }

  .state-label {
    font-size: 1.15rem;
    font-weight: 500;
    color: var(--primary-text-color);
  }

  .buttons {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    padding: 4px 16px 16px;
    justify-content: center;
  }

  .btn {
    flex: 1;
    min-width: 72px;
    padding: 10px 12px;
    border: none;
    border-radius: var(--ha-card-border-radius, 12px);
    cursor: pointer;
    font-size: 0.875rem;
    font-weight: 500;
    font-family: var(--mdc-typography-button-font-family, inherit);
    letter-spacing: 0.04em;
    transition: filter 0.15s;
  }
  .btn:hover  { filter: brightness(1.12); }
  .btn:active { filter: brightness(0.88); }
  .btn.arm    { background: var(--primary-color); color: var(--text-primary-color, #fff); }
  .btn.disarm { background: var(--error-color, #e53935); color: #fff; }
`;

class OrisecAlarmPanelCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._renderKey = null;
  }

  static getStubConfig() {
    return { entity: "alarm_control_panel.home" };
  }

  getCardSize() {
    return 4;
  }

  setConfig(config) {
    if (!config.entity) throw new Error("entity is required");
    this._config = config;
    if (this._hass) this._update();
  }

  set hass(hass) {
    this._hass = hass;
    this._update();
  }

  _update() {
    if (!this._config || !this._hass) return;
    const stateObj = this._hass.states[this._config.entity];
    if (!stateObj) {
      this._renderError(`Entity not found: ${this._config.entity}`);
      return;
    }
    // Skip re-render when nothing has changed.
    const key = stateObj.last_updated + stateObj.state + JSON.stringify(stateObj.attributes);
    if (key === this._renderKey) return;
    this._renderKey = key;
    this._render(stateObj);
  }

  _render(stateObj) {
    const { state, attributes: a } = stateObj;
    const features = a.supported_features || 0;
    const name = this._config.name || a.friendly_name || this._config.entity;
    const style = STATE_STYLE[state] || { color: "var(--secondary-text-color)", icon: "mdi:shield", blink: false };
    const stateLabel = this._stateLabel(state, a);

    const isArmed = ["armed_away", "armed_home", "armed_night", "armed_vacation", "triggered", "pending"].includes(state);
    const isTransitioning = state === "arming" || state === "pending";

    const buttons = [];
    if (isArmed && !isTransitioning) {
      buttons.push({ label: "Disarm", svc: "disarm", cls: "disarm" });
    }
    if (!isArmed) {
      if (features & FEATURE.ARM_AWAY)
        buttons.push({ label: "Full Set",                       svc: "arm_away",     cls: "arm" });
      if (features & FEATURE.ARM_HOME)
        buttons.push({ label: a.home_mode    || "Part Set",     svc: "arm_home",     cls: "arm" });
      if (features & FEATURE.ARM_NIGHT)
        buttons.push({ label: a.night_mode   || "Part Set 2",   svc: "arm_night",    cls: "arm" });
      if (features & FEATURE.ARM_VACATION)
        buttons.push({ label: a.vacation_mode || "Part Set 3",  svc: "arm_vacation", cls: "arm" });
    }

    const btnHtml = buttons
      .map(b => `<button class="btn ${b.cls}" data-svc="${b.svc}">${b.label}</button>`)
      .join("");

    this.shadowRoot.innerHTML = `
      <style>${STYLES}</style>
      <ha-card>
        <div class="name">${name}</div>
        <div class="body">
          <div class="badge ${style.blink ? "blink" : ""}" style="background:${style.color}">
            <ha-icon icon="${style.icon}"></ha-icon>
          </div>
          <div class="state-label">${stateLabel}</div>
        </div>
        <div class="buttons">${btnHtml}</div>
      </ha-card>`;

    this.shadowRoot.querySelectorAll(".btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        this._hass.callService("alarm_control_panel", btn.dataset.svc, {
          entity_id: this._config.entity,
        });
      });
    });
  }

  _stateLabel(state, a) {
    switch (state) {
      case "disarmed":       return "Disarmed";
      case "armed_away":     return "Full Set";
      case "armed_home":     return `Set \u2013 ${a.home_mode     || "Part 1"}`;
      case "armed_night":    return `Set \u2013 ${a.night_mode    || "Part 2"}`;
      case "armed_vacation": return `Set \u2013 ${a.vacation_mode || "Part 3"}`;
      case "arming":         return "Setting\u2026";
      case "pending":        return "Entry delay\u2026";
      case "triggered":      return "Alarm!";
      default:               return state;
    }
  }

  _renderError(msg) {
    this.shadowRoot.innerHTML = `
      <ha-card>
        <div style="padding:16px;color:var(--error-color,red)">${msg}</div>
      </ha-card>`;
  }
}

customElements.define("orisec-alarm-panel-card", OrisecAlarmPanelCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "orisec-alarm-panel-card",
  name: "Orisec Alarm Panel",
  description: "Alarm control panel card with Orisec arm mode names",
  preview: true,
});
