/**
 * Orisec Virtual Keypad Card
 *
 * Emulates the physical alarm panel keypad with a live LCD display.
 * Communicates via WebSocket subscription for LCD updates and
 * WebSocket commands for keypad button presses.
 *
 * Usage:
 *   type: custom:orisec-keypad-card
 *   name: Panel Keypad   # optional
 *   entry_id: abc123     # optional, auto-detected if single panel
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

const STYLES = `
  :host { display: block; }
  ha-card { overflow: hidden; }

  .header {
    padding: 16px 16px 0;
    font-size: 0.875rem;
    font-weight: 500;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    color: var(--secondary-text-color);
  }

  .lcd {
    background: #001832;
    color: #a0e8a0;
    font-family: "Courier New", "Lucida Console", monospace;
    font-size: 15px;
    line-height: 1.55;
    padding: 10px 14px;
    margin: 12px;
    border-radius: 8px;
    border: 2px solid #003060;
    min-height: 96px;
    white-space: pre;
    letter-spacing: 0.5px;
    box-shadow: inset 0 0 20px rgba(0, 24, 50, 0.6);
  }
  .lcd .line {
    display: block;
    min-height: 1.55em;
  }

  .keypad {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 6px;
    padding: 4px 12px 14px;
  }

  .key {
    padding: 12px 4px;
    border: 1px solid var(--divider-color, #e0e0e0);
    border-radius: 8px;
    font-size: 14px;
    font-weight: 500;
    cursor: pointer;
    text-align: center;
    background: var(--card-background-color, #fff);
    color: var(--primary-text-color);
    font-family: var(--mdc-typography-button-font-family, inherit);
    transition: filter 0.1s, transform 0.08s;
    user-select: none;
    -webkit-tap-highlight-color: transparent;
  }
  .key:hover  { filter: brightness(0.95); }
  .key:active { filter: brightness(0.85); transform: scale(0.96); }
  .key.num    { font-size: 20px; font-weight: 600; }
  .key.danger {
    background: var(--error-color, #e53935);
    color: #fff;
    border-color: var(--error-color, #e53935);
  }
  .key.action {
    background: var(--primary-color);
    color: var(--text-primary-color, #fff);
    border-color: var(--primary-color);
  }
  .key.nav {
    background: var(--secondary-background-color, #f5f5f5);
    font-size: 18px;
  }
  .key.blank {
    visibility: hidden;
    pointer-events: none;
  }

  .status {
    text-align: center;
    padding: 8px 12px 12px;
    font-size: 0.8rem;
    color: var(--secondary-text-color);
  }
  .status.error { color: var(--error-color, #e53935); }
`;

class OrisecKeypadCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config = null;
    this._hass = null;
    this._unsubscribe = null;
    this._lcdLines = ["", "", "", ""];
    this._entryId = null;
    this._connected = false;
    this._rendered = false;
  }

  static getStubConfig() {
    return {};
  }

  getCardSize() {
    return 6;
  }

  setConfig(config) {
    this._config = config;
    this._entryId = config.entry_id || null;
    this._render();
  }

  set hass(hass) {
    const firstSet = !this._hass;
    this._hass = hass;
    if (firstSet) this._subscribe();
  }

  connectedCallback() {
    if (this._hass && !this._unsubscribe) this._subscribe();
  }

  disconnectedCallback() {
    this._teardown();
  }

  _teardown() {
    if (this._unsubscribe) {
      this._unsubscribe();
      this._unsubscribe = null;
    }
    this._connected = false;
  }

  async _subscribe() {
    if (!this._hass || this._unsubscribe) return;

    try {
      if (!this._entryId) {
        const entries = await this._hass.connection.sendMessagePromise({
          type: "orisec/keypad/entries",
        });
        if (entries && entries.length > 0) {
          this._entryId = entries[0].entry_id;
        } else {
          this._setStatus("No Orisec panel found", true);
          return;
        }
      }

      const msg = { type: "orisec/keypad/subscribe" };
      if (this._entryId) msg.entry_id = this._entryId;

      this._unsubscribe = await this._hass.connection.subscribeMessage(
        (event) => this._handleLcdUpdate(event),
        msg,
      );
      this._connected = true;
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
      const msg = { type: "orisec/keypad/press", char: char };
      if (this._entryId) msg.entry_id = this._entryId;
      await this._hass.connection.sendMessagePromise(msg);
    } catch (err) {
      this._setStatus("Send failed: " + (err.message || err), true);
    }
  }

  _render() {
    const name = (this._config && this._config.name) || "Keypad";

    const buttonsHtml = KEYPAD_BUTTONS.map((btn, i) =>
      `<button class="key ${btn.cls}" data-idx="${i}">${btn.label}</button>`
    ).join("");

    this.shadowRoot.innerHTML = `
      <style>${STYLES}</style>
      <ha-card>
        <div class="header">${name}</div>
        <div class="lcd">${
          [0, 1, 2, 3].map(i => `<span class="line line-${i}"></span>`).join("")
        }</div>
        <div class="keypad">${buttonsHtml}</div>
        <div class="status"></div>
      </ha-card>`;

    this.shadowRoot.querySelector(".keypad").addEventListener("click", (e) => {
      const btn = e.target.closest(".key");
      if (!btn) return;
      const idx = parseInt(btn.dataset.idx, 10);
      const def = KEYPAD_BUTTONS[idx];
      if (def && def.char) this._sendKey(def.char);
    });

    this._rendered = true;
    this._updateLcd();
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
    const el = this.shadowRoot.querySelector(".status");
    if (!el) return;
    el.textContent = text;
    el.className = isError ? "status error" : "status";
  }
}

customElements.define("orisec-keypad-card", OrisecKeypadCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "orisec-keypad-card",
  name: "Orisec Keypad",
  description: "Virtual keypad with LCD display for Orisec alarm panels",
  preview: false,
});
