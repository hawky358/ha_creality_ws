/* K1C / Creality Printer Card — composite card + lightweight GUI editor
 * Dependencies: mushroom, stack-in-card, card-mod
 */

const CARD_TAG = "k1c-printer-card";
const EDITOR_TAG = "k1c-printer-card-editor";

// ---- global helpers (memoized) ----
let HELPERS_PROMISE;
function getHelpers() {
  if (!HELPERS_PROMISE) HELPERS_PROMISE = window.loadCardHelpers();
  return HELPERS_PROMISE;
}

// ---- defaults ----
const DEFAULT_ENTITIES = {
  // friendly name (user-configurable)
  name: "3D Printer",

  // entities
  camera: "camera.k1c_printer_camera",
  status: "sensor.k1c_print_status",
  progress: "sensor.k1c_print_progress",
  time_left: "sensor.k1c_print_time_left",
  nozzle: "sensor.k1c_nozzle_temperature",
  bed: "sensor.k1c_bed_temperature",
  box: "sensor.k1c_box_temperature",
  layer: "sensor.k1c_working_layer",
  total_layers: "sensor.k1c_total_layers",
  light: "switch.k1c_light",
  pause_btn: "button.k1c_pause_print",
  resume_btn: "button.k1c_resume_print",
  stop_btn: "button.k1c_stop_print",
};

function buildPreset(cfg) {
  const ent = (k) => cfg[k] || DEFAULT_ENTITIES[k];

  const secondary = `
    {% set st = (states('${ent("status")}') or 'unknown')|lower %}
    {% set pct = (states('${ent("progress")}')|int(0)) %}
    {% if st in ['printing','resuming','pausing','paused'] %}{{ pct }}% {{ st|title }}
    {% elif st in ['idle','completed','error','unknown','off'] %}{{ st|title }}
    {% else %}Unknown{% endif %}
  `;

  const icon = `
    {% set st = (states('${ent("status")}') or 'unknown')|lower %}
    {% if st in ['off','unknown'] %}mdi:printer-3d-off
    {% elif st in ['printing','resuming','pausing','paused'] %}mdi:printer-3d-nozzle
    {% elif st == 'error' %}mdi:close-octagon
    {% else %}mdi:printer-3d
    {% endif %}
  `;

  const icon_color = `
    {% set st = (states('${ent("status")}') or 'unknown')|lower %}
    {% if st in ['off','unknown'] %}grey
    {% elif st in ['paused','pausing'] %}#fc6d09
    {% elif st == 'error' %}red
    {% elif st in ['printing','resuming'] %}var(--primary-color)
    {% elif st in ['idle','completed'] %}green
    {% else %}grey
    {% endif %}
  `;

  const ring_style = `
    {% set st = (states('${ent("status")}') or 'unknown')|lower %}
    {% set pct = states('${ent("progress")}')|int(0) %}
    .shape { --icon-size: 80px; }
    ha-state-icon { --icon-symbol-size: 40px; width: 40px; height: 40px; }
    .shape {
      {% if st in ['printing','resuming','pausing','paused'] %}
        background:
          radial-gradient(var(--card-background-color) 60%, transparent 0),
          conic-gradient(var(--primary-color) {{ pct }}%, rgba(var(--rgb-grey),0.25) {{ pct }}%);
      {% else %} background: none; {% endif %}
    }
  `;

  const time_fmt = `
    {% set s = states('${ent("time_left")}')|int(0) %}
    {% set h = (s // 3600) %}{% set m = (s % 3600) // 60 %}{% set sec = s % 60 %}
    {% if h > 0 %}{{ '%d:%02d:%02d'|format(h, m, sec) }}
    {% elif m > 0 %}{{ '%d:%02d'|format(m, sec) }}
    {% else %}{{ sec }}s{% endif %}
  `;

  return {
    type: "custom:stack-in-card",
    cards: [
      {
        type: "horizontal-stack",
        cards: [
          {
            type: "custom:mushroom-template-card",
            entity: ent("camera"),
            primary: cfg.name || DEFAULT_ENTITIES.name,
            secondary, icon, icon_color,
            tap_action: { action: "more-info" },
            card_mod: {
              style: {
                "mushroom-shape-icon$": ring_style,
                ".": "ha-card { padding: 10px 12px 0 12px; --ha-card-border-width: 0; }",
              },
            },
          },
          {
            type: "custom:mushroom-chips-card",
            alignment: "end",
            chips: [
              // --- PAUSE: only when actively printing (never off/unknown) ---
              {
                type: "conditional",
                conditions: [
                  {
                    condition: "or",
                    conditions: [
                      { condition: "state", entity: ent("status"), state: "printing" },
                      { condition: "state", entity: ent("status"), state: "resuming" },
                      { condition: "state", entity: ent("status"), state: "pausing" },
                    ],
                  },
                ],
                chip: {
                  type: "entity",
                  entity: ent("pause_btn"),
                  icon: "mdi:pause",
                  content_info: "none",
                  tap_action: { action: "toggle" },
                  card_mod: { style: "ha-card{--chip-background: rgba(var(--rgb-orange),0.9); --icon-color: rgb(var(--rgb-white)); border:none}" },
                },
              },

              // --- RESUME: only when paused (never off/unknown) ---
              {
                type: "conditional",
                conditions: [
                  { condition: "state", entity: ent("status"), state: "paused" },
                ],
                chip: {
                  type: "entity",
                  entity: ent("resume_btn"),
                  icon: "mdi:play",
                  content_info: "none",
                  tap_action: { action: "toggle" },
                  card_mod: { style: "ha-card{--chip-background: rgba(var(--rgb-green),0.9); --icon-color: rgb(var(--rgb-white)); border:none}" },
                },
              },

              // --- STOP: only when in any active/paused state (never off/unknown) ---
              {
                type: "conditional",
                conditions: [
                  {
                    condition: "or",
                    conditions: [
                      { condition: "state", entity: ent("status"), state: "printing" },
                      { condition: "state", entity: ent("status"), state: "resuming" },
                      { condition: "state", entity: ent("status"), state: "pausing" },
                      { condition: "state", entity: ent("status"), state: "paused" },
                    ],
                  },
                ],
                chip: {
                  type: "entity",
                  entity: ent("stop_btn"),
                  icon: "mdi:stop",
                  content_info: "none",
                  tap_action: { action: "toggle" },
                  card_mod: { style: "ha-card{--chip-background: rgba(var(--rgb-red),0.95); --icon-color: rgb(var(--rgb-white)); border:none}" },
                },
              },

              // --- LIGHT: hide completely when printer is off/unknown ---
              {
                type: "conditional",
                conditions: [
                  { condition: "state_not", entity: ent("status"), state: "off" },
                  { condition: "state_not", entity: ent("status"), state: "unknown" },
                ],
                chip: {
                  type: "template",
                  entity: ent("light"),
                  icon: "mdi:lightbulb",
                  content: "",
                  icon_color: `
                    {% set st = (states('${ent("status")}') or 'unknown')|lower %}
                    {% if st in ['off','unknown'] %}lightgrey
                    {% elif is_state('${ent("light")}','on') %}orange
                    {% else %}lightgrey{% endif %}
                  `,
                  tap_action: { action: "toggle" },
                  card_mod: {
                    style: `
                      ha-card{
                        border:none;
                        {% set st = (states('${ent("status")}') or 'unknown')|lower %}
                        {% if st in ['off','unknown'] -%}
                          --chip-background: rgba(var(--rgb-grey),0.35);
                          pointer-events: none; opacity: 0.6;
                        {%- elif is_state('${ent("light")}','on') -%}
                          --chip-background: rgba(var(--rgb-yellow),0.95);
                        {%- else -%}
                          --chip-background: rgba(var(--rgb-grey),0.35);
                        {%- endif %}
                      }
                    `,
                  },
                },
              },
            ],
            card_mod: {
              style: "ha-card{ --ha-card-border-width: 0; padding: 24px 28px 0 0; --chip-spacing: 8px; }",
            },
          },
        ],
      },

      // Telemetry row
      {
        type: "custom:mushroom-chips-card",
        alignment: "center",
        chips: [
          { type: "template", icon: "mdi:printer-3d-nozzle-heat", content: `{{ (states('${ent("nozzle")}')|float(0))|round(1) }} °C` },
          { type: "template", icon: "mdi:heating-coil",           content: `{{ (states('${ent("bed")}')|float(0))|round(1) }} °C` },
          { type: "template", icon: "mdi:thermometer",            content: `{{ (states('${ent("box")}')|float(0))|round(1) }} °C` },
          { type: "template", icon: "mdi:progress-clock",         content: time_fmt },
          { type: "template", icon: "mdi:layers-triple",          content: `L {{ states('${ent("layer")}') }}/{{ states('${ent("total_layers")}') }}` },
        ],
        card_mod: {
          style: `
            ha-card{ --ha-card-border-width: 0; padding: 6px 8px 10px 8px; --chip-spacing: 8px; }
            mushroom-chip-set { display: flex; justify-content: center; flex-wrap: wrap; }
            mushroom-chip { flex: 1 0 120px; max-width: 160px; }
          `,
        },
      },
    ],
    card_mod: { style: "ha-card{border-radius:16px; overflow:hidden}" },
  };
}

class K1CPrinterCard extends HTMLElement {
  async setConfig(config) {
    this._cfg = { ...config };
    if (!this._root) this._root = this.attachShadow({ mode: "open" });
    if (!this._helpers) this._helpers = await getHelpers();

    if (this._el && this._el.setConfig) {
      try { this._el.setConfig(buildPreset(this._cfg)); return; } catch (_) {}
    }

    const el = await this._helpers.createCardElement(buildPreset(this._cfg));
    el.hass = this._hass;
    this._el = el;
    this._root.replaceChildren(el);
  }

  set hass(hass) { this._hass = hass; if (this._el) this._el.hass = hass; }
  getCardSize() { return 3; }

  static getConfigElement() { return document.createElement(EDITOR_TAG); }
  static getStubConfig() { return { ...DEFAULT_ENTITIES }; }
}
customElements.define(CARD_TAG, K1CPrinterCard);

// ---------- Lightweight GUI editor ----------
class K1CPrinterCardEditor extends HTMLElement {
  set hass(hass) { this._hass = hass; if (this._form) this._form.hass = hass; }
  setConfig(config) { this._cfg = { ...DEFAULT_ENTITIES, ...(config || {}) }; this._render(); }

  connectedCallback() { if (!this._root) { this._root = this.attachShadow({ mode: "open" }); this._render(); } }

  _render() {
    if (!this._root) return;
    if (!this._form) {
      this._root.innerHTML = `<ha-form id="f"></ha-form>`;
      this._form = this._root.getElementById("f");
      this._form.hass = this._hass;
      this._form.addEventListener("value-changed", this._onChange.bind(this));
    }
    this._form.schema = [
      { name: "Name:",         selector: { text: {} }, label: "Printer Name" },
      { name: "Camera:",      selector: { entity: { domain: "camera" } }, label: "Camera" },
      { name: "Status:",      selector: { entity: { domain: "sensor" } }, label: "Print Status" },
      { name: "Progress:",    selector: { entity: { domain: "sensor" } }, label: "Print Progress (%)" },
      { name: "TIme left:",   selector: { entity: { domain: "sensor" } }, label: "Time Left (seconds)" },
      { name: "Nozzle temperature:",      selector: { entity: { domain: "sensor" } }, label: "Nozzle Temp" },
      { name: "Bed temperature:",         selector: { entity: { domain: "sensor" } }, label: "Bed Temp" },
      { name: "Enclosure temperature:",         selector: { entity: { domain: "sensor" } }, label: "Box Temp" },
      { name: "Current layer:",       selector: { entity: { domain: "sensor" } }, label: "Working Layer" },
      { name: "Total layers:",selector: { entity: { domain: "sensor" } }, label: "Total Layers" },
      { name: "Light:",       selector: { entity: { domain: "switch" } }, label: "Light Switch" },
      { name: "Pause button:",   selector: { entity: { domain: "button" } }, label: "Pause Button" },
      { name: "Resume button:",  selector: { entity: { domain: "button" } }, label: "Resume Button" },
      { name: "Stop button:",    selector: { entity: { domain: "button" } }, label: "Stop Button" },
    ];
    this._form.data = this._cfg || DEFAULT_ENTITIES;
  }

  _onChange(ev) {
    const val = ev.detail?.value || {};
    this._cfg = val;
    clearTimeout(this._t);
    this._t = setTimeout(() => {
      this.dispatchEvent(new CustomEvent("config-changed", { detail: { config: val } }));
    }, 120);
  }
}
customElements.define(EDITOR_TAG, K1CPrinterCardEditor);

// Card picker registration
window.customCards = window.customCards || [];
window.customCards.push({
  type: CARD_TAG,
  name: "K1C / Creality Printer Card",
  description: "Compact Mushroom + card-mod + stack-in-card preset for Creality Klipper printers.",
});