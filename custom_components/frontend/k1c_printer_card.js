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

function buildPreset(cfg) {
  // Use user's config directly.
  const name = cfg.name || "3D Printer";
  const camera_entity = cfg.camera || "";
  const status_entity = cfg.status || "";
  const progress_entity = cfg.progress || "";
  const time_left_entity = cfg.time_left || "";
  const nozzle_entity = cfg.nozzle || "";
  const bed_entity = cfg.bed || "";
  const box_entity = cfg.box || "";
  const layer_entity = cfg.layer || "";
  const total_layers_entity = cfg.total_layers || "";
  const light_entity = cfg.light || "";
  const pause_btn_entity = cfg.pause_btn || "";
  const resume_btn_entity = cfg.resume_btn || "";
  const stop_btn_entity = cfg.stop_btn || "";

  const secondary = `
    {% set st = (states('${status_entity}') or 'unknown')|lower %}
    {% set pct = (states('${progress_entity}')|int(0)) %}
    {% if st in ['printing','resuming','pausing','paused'] %}
      {{ pct }}% {{ st|title }}
    {% else %}
      {{ st|replace('_', ' ')|title }}
    {% endif %}
  `;

  const icon = `
    {% set st = (states('${status_entity}') or 'unknown')|lower %}
    {% if st in ['off', 'unknown', 'stopped'] %}mdi:printer-3d-off
    {% elif st in ['printing', 'resuming', 'pausing', 'paused'] %}mdi:printer-3d-nozzle
    {% elif st == 'error' %}mdi:close-octagon
    {% elif st == 'self-testing' %}mdi:cogs
    {% else %}mdi:printer-3d
    {% endif %}
  `;

  const icon_color = `
    {% set st = (states('${status_entity}') or 'unknown')|lower %}
    {% if st in ['off', 'unknown', 'stopped'] %}grey
    {% elif st in ['paused', 'pausing'] %}#fc6d09
    {% elif st == 'error' %}red
    {% elif st in ['printing', 'resuming', 'processing'] %}var(--primary-color)
    {% elif st in ['idle', 'completed'] %}green
    {% elif st == 'self-testing' %}blue
    {% else %}grey
    {% endif %}
  `;

  const ring_style = `
    {% set st = (states('${status_entity}') or 'unknown')|lower %}
    {% set pct = states('${progress_entity}')|int(0) %}
    .shape { --icon-size: 80px; }
    ha-state-icon { --icon-symbol-size: 40px; width: 40px; height: 40px; }
    .shape {
      {% if st in ['printing', 'resuming', 'pausing', 'paused'] %}
        background:
          radial-gradient(var(--card-background-color) 60%, transparent 0),
          conic-gradient(var(--primary-color) {{ pct }}%, rgba(var(--rgb-grey),0.25) {{ pct }}%);
      {% else %} background: none; {% endif %}
    }
  `;

  const time_fmt = `
    {% set s = states('${time_left_entity}')|int(0) %}
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
            entity: camera_entity,
            primary: name,
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
              // PAUSE
              {
                type: "conditional",
                conditions: [{ condition: "state", entity: status_entity, state: "printing" }],
                chip: { type: "entity", entity: pause_btn_entity, icon: "mdi:pause", content_info: "none", tap_action: { action: "toggle" }, card_mod: { style: "ha-card{--chip-background: rgba(var(--rgb-orange),0.9); --icon-color: rgb(var(--rgb-white)); border:none}" } },
              },
              // RESUME
              {
                type: "conditional",
                conditions: [{ condition: "state", entity: status_entity, state: "paused" }],
                chip: { type: "entity", entity: resume_btn_entity, icon: "mdi:play", content_info: "none", tap_action: { action: "toggle" }, card_mod: { style: "ha-card{--chip-background: rgba(var(--rgb-green),0.9); --icon-color: rgb(var(--rgb-white)); border:none}" } },
              },
              // STOP (visible during self-test)
              {
                type: "conditional",
                conditions: [{ condition: "or", conditions: [
                  { condition: "state", entity: status_entity, state: "printing" },
                  { condition: "state", entity: status_entity, state: "paused" },
                  { condition: "state", entity: status_entity, state: "self-testing" },
                ] }],
                chip: { type: "entity", entity: stop_btn_entity, icon: "mdi:stop", content_info: "none", tap_action: { action: "toggle" }, card_mod: { style: "ha-card{--chip-background: rgba(var(--rgb-red),0.95); --icon-color: rgb(var(--rgb-white)); border:none}" } },
              },
              // SPACER
              {
                type: "template",
                content: "&nbsp;",
                card_mod: { style: `ha-card{ border:none !important; background: none !important; box-shadow: none !important; visibility: hidden; pointer-events: none; min-width: 42px; height: var(--chip-height, 40px); margin: 0; padding: 0; }`},
              },
              // --- THE FIX: Bypassing the conditional chip ---
              // This chip is now a simple template chip that is ALWAYS rendered.
              // Its visibility is controlled by the CSS 'display' property inside card_mod.
              {
                type: "template",
                entity: light_entity,
                icon: "mdi:lightbulb",
                content: "",
                tap_action: { action: "toggle" },
                card_mod: {
                  style: `
                    {% set st = (states('${status_entity}') or 'unknown')|lower %}
                    ha-card {
                      /* This is the new visibility logic */
                      display: {% if st in ['off', 'unknown'] %} none {% else %} flex {% endif %};

                      border: none !important;
                      {% if is_state('${light_entity}','on') %}
                        --chip-background: rgba(var(--rgb-yellow),0.95);
                        --icon-color: rgb-orange;
                      {% else %}
                        --chip-background: rgba(var(--rgb-grey),0.35);
                        --icon-color: black;
                      {% endif %}
                    }
                  `,
                },
              },
            ],
            card_mod: { style: "ha-card{ --ha-card-border-width: 0; padding: 24px 28px 0 0; --chip-spacing: 8px; }" },
          },
        ],
      },
      // Telemetry row (unchanged)
      {
        type: "custom:mushroom-chips-card",
        alignment: "center",
        chips: [
          { type: "template", icon: "mdi:printer-3d-nozzle-heat", content: `{{ (states('${nozzle_entity}')|float(0))|round(1) }} °C` },
          { type: "template", icon: "mdi:heating-coil",           content: `{{ (states('${bed_entity}')|float(0))|round(1) }} °C` },
          { type: "template", icon: "mdi:thermometer",            content: `{{ (states('${box_entity}')|float(0))|round(1) }} °C` },
          { type: "template", icon: "mdi:progress-clock",         content: time_fmt },
          { type: "template", icon: "mdi:layers-triple",          content: `{{ states('${layer_entity}') }}/{{ states('${total_layers_entity}') }}` },
        ],
        card_mod: { style: `ha-card{ --ha-card-border-width: 0; padding: 6px 8px 10px 8px; --chip-spacing: 4px; } mushroom-chip-set { display: flex; justify-content: center; flex-wrap: wrap; } mushroom-chip { flex: 1 0 120px; max-width: 160px; }` },
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
  static getStubConfig() {
    return {
      name: "3D Printer",
      camera: "", status: "", progress: "", time_left: "",
      nozzle: "", bed: "", box: "",
      layer: "", total_layers: "",
      light: "", pause_btn: "", resume_btn: "", stop_btn: "",
    };
  }
}
customElements.define(CARD_TAG, K1CPrinterCard);

class K1CPrinterCardEditor extends HTMLElement {
  set hass(hass) { this._hass = hass; if (this._form) this._form.hass = hass; }
  setConfig(config) {
    this._cfg = { ...(config || {}) };
    this._render();
  }

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
      { name: "name",         label: "Printer Name", selector: { text: {} } },
      { name: "camera",       label: "Camera", selector: { entity: { domain: "camera" } } },
      { name: "status",       label: "Print Status Sensor", selector: { entity: { domain: "sensor" } } },
      { name: "progress",     label: "Print Progress Sensor (%)", selector: { entity: { domain: "sensor" } } },
      { name: "time_left",    label: "Time Left Sensor (seconds)", selector: { entity: { domain: "sensor" } } },
      { name: "nozzle",       label: "Nozzle Temperature Sensor", selector: { entity: { domain: "sensor" } } },
      { name: "bed",          label: "Bed Temperature Sensor", selector: { entity: { domain: "sensor" } } },
      { name: "box",          label: "Enclosure Temperature Sensor", selector: { entity: { domain: "sensor" } } },
      { name: "layer",        label: "Current Layer Sensor", selector: { entity: { domain: "sensor" } } },
      { name: "total_layers", label: "Total Layers Sensor", selector: { entity: { domain: "sensor" } } },
      { name: "light",        label: "Light Switch", selector: { entity: { domain: "switch" } } },
      { name: "pause_btn",    label: "Pause Button", selector: { entity: { domain: "button" } } },
      { name: "resume_btn",   label: "Resume Button", selector: { entity: { domain: "button" } } },
      { name: "stop_btn",     label: "Stop Button", selector: { entity: { domain: "button" } } },
    ];
    this._form.data = this._cfg;
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