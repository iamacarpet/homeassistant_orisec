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

const ICON_MAP = {
  127: "\u25C0", 128: "E", 155: ":", 156: ".",
  159: "\u2612", 160: "\u2610", 163: "\u25B2", 164: "\u25BC",
  165: "\u25B6", 166: "\u25C0", 170: "\u2731", 172: "\u25BC", 173: "\u25B2",
};

const LCD_WIDTH = 320;
const LCD_HEIGHT = 96;
const LCD_LINE_H = 24;
const LCD_FONT = "14px 'Courier New', 'Lucida Console', monospace";
const LCD_BG = "#001832";
const LCD_FG = "#e0e0e0";
const LCD_INV_BG = "#e0e0e0";
const LCD_INV_FG = "#001832";

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
  ctx.font = LCD_FONT;
  ctx.textBaseline = "middle";

  if (!raw || raw.length === 0) return;

  const lines = [[], [], [], []];
  const lineAligns = ["left", "left", "left", "left"];
  let cur = -1;
  let inverted = false;

  let i = 0;
  while (i < raw.length) {
    const b = raw[i];
    if (b === 17) {
      cur = cur === -1 ? 0 : Math.min(cur + 1, 3);
      lines[cur] = [];
      lineAligns[cur] = "left";
      inverted = false;
    } else if (b >= 18 && b <= 21) {
      cur = b - 18;
      lines[cur] = [];
      lineAligns[cur] = "left";
      inverted = false;
    } else if (b === 5) {
      inverted = false;
    } else if (b === 6) {
      inverted = true;
    } else if (b === 10 && cur >= 0) {
      lineAligns[cur] = "center";
    } else if (b === 11 && cur >= 0) {
      lineAligns[cur] = "right";
    } else if (b === 12 && cur >= 0) {
      const ts = (time[0] < 10 ? "0" : "") + time[0] + ":" +
                 (time[1] < 10 ? "0" : "") + time[1] + "." +
                 (time[2] < 10 ? "0" : "") + time[2];
      for (let c = 0; c < ts.length; c++) {
        lines[cur].push({ ch: ts[c], inv: inverted });
      }
    } else if (b === 14) {
      if (cur >= 0 && i + 4 < raw.length) {
        const pVal = raw[i + 1];
        const pMax = raw[i + 2] || 1;
        lines[cur].push({ progress: true, value: pVal, max: pMax, inv: inverted });
      }
      i += 4;
    } else if (b === 7 || b === 8 || b === 16 || b === 26) {
      i++;
    } else if (b >= 22 && b <= 25) {
      // font size markers
    } else if (b >= 32 && b <= 125 && cur >= 0) {
      lines[cur].push({ ch: String.fromCharCode(b), inv: inverted });
    } else if (b > 126 && b <= 173 && cur >= 0) {
      const icon = ICON_MAP[b];
      if (icon) lines[cur].push({ ch: icon, inv: inverted });
    }
    i++;
  }

  for (let line = 0; line < 4; line++) {
    const segments = lines[line];
    if (!segments || segments.length === 0) continue;

    const y = line * LCD_LINE_H + LCD_LINE_H / 2;
    const hasProgress = segments.find(s => s.progress);

    if (hasProgress) {
      const s = hasProgress;
      const barW = LCD_WIDTH - 16;
      const barH = 8;
      const barY = y - barH / 2;
      ctx.strokeStyle = LCD_FG;
      ctx.lineWidth = 1;
      ctx.strokeRect(8, barY, barW, barH);
      const fill = Math.min(s.value / (s.max || 1), 1) * barW;
      ctx.fillStyle = LCD_FG;
      ctx.fillRect(8, barY, fill, barH);
      continue;
    }

    const text = segments.map(s => s.ch).join("");
    const textW = ctx.measureText(text).width;
    let x = 8;
    if (lineAligns[line] === "center") {
      x = (LCD_WIDTH - textW) / 2;
    } else if (lineAligns[line] === "right") {
      x = LCD_WIDTH - textW - 8;
    }

    let currentInv = null;
    let run = "";
    let runX = x;

    function flushRun(inv) {
      if (!run) return;
      const rw = ctx.measureText(run).width;
      if (inv) {
        ctx.fillStyle = LCD_INV_BG;
        ctx.fillRect(runX, y - LCD_LINE_H / 2 + 2, rw, LCD_LINE_H - 4);
        ctx.fillStyle = LCD_INV_FG;
        ctx.font = "bold " + LCD_FONT;
      } else {
        ctx.fillStyle = LCD_FG;
        ctx.font = LCD_FONT;
      }
      ctx.fillText(run, runX, y);
      if (inv) ctx.font = LCD_FONT;
      run = "";
    }

    for (const seg of segments) {
      if (seg.inv !== currentInv) {
        flushRun(currentInv);
        currentInv = seg.inv;
        runX = x + ctx.measureText(text.substring(0, segments.indexOf(seg))).width;
      }
      run += seg.ch;
    }
    flushRun(currentInv);
  }
}

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

  .lcd-container {
    position: relative;
    margin: 12px;
  }
  .lcd-canvas {
    display: block;
    width: 100%;
    max-width: 320px;
    margin: 0 auto;
    border-radius: 8px;
    border: 2px solid #003060;
    box-shadow: inset 0 0 20px rgba(0, 24, 50, 0.6);
    background: #001832;
  }
  .lcd-overlay {
    position: absolute;
    top: 0; left: 0; right: 0; bottom: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    background: #001832;
    border-radius: 8px;
    border: 2px solid #003060;
    cursor: pointer;
    transition: filter 0.15s;
    max-width: 320px;
    margin: 0 auto;
  }
  .lcd-overlay:hover { filter: brightness(1.1); }
  .lcd-overlay-text {
    color: #a0e8a0;
    font-family: "Courier New", monospace;
    font-size: 14px;
    text-align: center;
  }
  .lcd-loading {
    position: absolute;
    top: 0; left: 0; right: 0; bottom: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    background: #001832;
    border-radius: 8px;
    border: 2px solid #003060;
    max-width: 320px;
    margin: 0 auto;
  }
  .lcd-loading-text {
    color: #a0e8a0;
    font-family: "Courier New", monospace;
    font-size: 14px;
    animation: blink-text 1.2s ease-in-out infinite;
  }
  @keyframes blink-text { 0%,100% { opacity:1 } 50% { opacity:0.3 } }

  .keypad-controls {
    display: flex;
    justify-content: center;
    padding: 0 12px 8px;
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
  .key.flash { filter: brightness(1.3); }

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
    this._entryId = null;
    this._connected = false;
    this._loading = false;
    this._rendered = false;
    this._lcdRaw = null;
    this._lcdTime = [0, 0, 0];
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
    this._hass = hass;
  }

  connectedCallback() {}

  disconnectedCallback() {
    this._teardown();
  }

  _teardown() {
    if (this._unsubscribe) {
      this._unsubscribe();
      this._unsubscribe = null;
    }
    this._connected = false;
    this._loading = false;
    this._lcdRaw = null;
  }

  async _connect() {
    if (!this._hass || this._unsubscribe) return;
    this._loading = true;
    this._updateView();

    try {
      if (!this._entryId) {
        const entries = await this._hass.connection.sendMessagePromise({
          type: "orisec/keypad/entries",
        });
        if (entries && entries.length > 0) {
          this._entryId = entries[0].entry_id;
        } else {
          this._loading = false;
          this._setStatus("No Orisec panel found", true);
          this._updateView();
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
      this._updateView();
    } catch (err) {
      this._loading = false;
      this._connected = false;
      this._updateView();
      this._setStatus("Connection failed: " + (err.message || err), true);
    }
  }

  _disconnect() {
    this._teardown();
    this._updateView();
  }

  _handleLcdUpdate(event) {
    this._lcdRaw = event.lcd_raw || [];
    this._lcdTime = event.time || [0, 0, 0];
    this._loading = false;
    this._updateView();
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

  _render() {
    const name = (this._config && this._config.name) || "Keypad";

    const buttonsHtml = KEYPAD_BUTTONS.map((btn, i) =>
      `<button class="key ${btn.cls}" data-idx="${i}">${btn.label}</button>`
    ).join("");

    this.shadowRoot.innerHTML = `
      <style>${STYLES}</style>
      <ha-card>
        <div class="header">${name}</div>
        <div class="lcd-container" id="lcd-container">
          <canvas class="lcd-canvas" id="lcd-canvas" width="320" height="96"></canvas>
          <div class="lcd-overlay" id="lcd-overlay">
            <div class="lcd-overlay-text">Click to connect</div>
          </div>
        </div>
        <div class="keypad-controls" id="keypad-controls" style="display:none">
          <button class="disconnect-btn" id="disconnect-btn">Disconnect</button>
        </div>
        <div class="keypad" id="keypad-grid" style="display:none">${buttonsHtml}</div>
        <div class="status" id="status"></div>
      </ha-card>`;

    this.shadowRoot.getElementById("lcd-overlay").addEventListener("click", () => {
      this._connect();
    });

    this.shadowRoot.getElementById("disconnect-btn").addEventListener("click", () => {
      this._disconnect();
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

    this._rendered = true;
  }

  _updateView() {
    if (!this._rendered) return;
    const overlay = this.shadowRoot.getElementById("lcd-overlay");
    const canvas = this.shadowRoot.getElementById("lcd-canvas");
    const controls = this.shadowRoot.getElementById("keypad-controls");
    const grid = this.shadowRoot.getElementById("keypad-grid");
    const container = this.shadowRoot.getElementById("lcd-container");
    const existingLoading = container.querySelector(".lcd-loading");

    if (!this._connected && !this._loading) {
      overlay.style.display = "flex";
      if (existingLoading) existingLoading.remove();
      canvas.style.display = "none";
      controls.style.display = "none";
      grid.style.display = "none";
    } else if (this._loading && !this._lcdRaw) {
      overlay.style.display = "none";
      canvas.style.display = "none";
      controls.style.display = "none";
      grid.style.display = "none";
      if (!existingLoading) {
        const loading = document.createElement("div");
        loading.className = "lcd-loading";
        loading.innerHTML = '<div class="lcd-loading-text">Loading, please wait...</div>';
        container.appendChild(loading);
      }
    } else {
      overlay.style.display = "none";
      if (existingLoading) existingLoading.remove();
      canvas.style.display = "block";
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
    const el = this.shadowRoot.getElementById("status");
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
