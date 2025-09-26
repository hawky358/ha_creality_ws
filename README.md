Here’s the updated **README.md** draft with that note clearly included. You can place it under **Status / Testing** so potential contributors see it immediately:

---

# Creality WebSocket Integration for Home Assistant

This custom [Home Assistant](https://www.home-assistant.io/) integration provides **native, low-latency WebSocket control and telemetry** for Creality K-series and compatible 3D printers. It exposes the printer’s live state, sensors, controls, and camera stream to Home Assistant and includes a ready-to-use Lovelace card for printer monitoring.

---

## Features

* **Direct WebSocket connection** to the printer, no cloud required.
* **Entities for telemetry and control**:

  * Status, progress, job time, layers, object count
  * Temperatures (bed, nozzle, chamber)
  * Speeds, flow rate, fans
  * Current position (X/Y/Z)
  * Current object / excluded objects
* **Controls**:

  * Pause, Resume, Stop print
  * Light toggle
  * Speed/flow tuning
  * Temperature and fan setpoints
* **MJPEG camera proxy** with relay via Home Assistant
* **Local push updates** (no polling)
* **Custom Lovelace card** (`k1c_printer_card.js`) with pause/resume/stop chips, temperatures, progress ring, and printer info

---

## Status / Testing

⚠️ This integration has been **tested only on Creality K1C**.
It may work on other **Creality Klipper-based printers with the stock web interface**, but this is unverified.

👉 **Looking for testers!**
If you own another supported model (e.g. K1, K1 Max, Sermoon D3, etc.), please install this integration and report results by opening an issue or PR on GitHub.

---

## Installation

### HACS (recommended)

1. Add this repository as a [custom repository](https://hacs.xyz/docs/faq/custom_repositories/) in HACS (`Integration` type).
2. Install **Creality WebSocket Integration**.
3. Restart Home Assistant.

### Manual

1. Copy the `custom_components/ha_creality_ws` directory to `<config>/custom_components/`.
2. Restart Home Assistant.

---

## Configuration

This integration uses a **config flow** (UI setup).

1. Navigate to **Settings → Devices & Services → Add Integration**.
2. Search for **Creality WebSocket Integration**.
3. Enter your printer’s hostname or IP.
4. Assign a friendly **name** (this will appear in the Lovelace card header).

Zeroconf discovery is supported; the printer should appear automatically if mDNS is working on your network.

---

## Entities

Entities are dynamically created depending on printer capabilities. Common ones:

### Sensors

* `sensor.<name>_print_status`
* `sensor.<name>_print_progress`
* `sensor.<name>_print_time_left`
* `sensor.<name>_print_job_time`
* `sensor.<name>_total_layers` / `sensor.<name>_working_layer`
* `sensor.<name>_nozzle_temperature`, `sensor.<name>_bed_temperature`, `sensor.<name>_box_temperature`
* `sensor.<name>_used_material_length`
* `sensor.<name>_position_x`, `position_y`, `position_z`
* `sensor.<name>_feedrate_pct`, `flowrate_pct`
* `sensor.<name>_system`, `sensor.<name>_object_count`, `sensor.<name>_current_object`

### Numbers

* `number.<name>_print_tuning_pct`
* `number.<name>_nozzle_target`
* `number.<name>_bed_target`
* `number.<name>_model_fan_pct`, `case_fan_pct`, `side_fan_pct`

### Switches

* `switch.<name>_light`

### Buttons

* `button.<name>_pause_print`
* `button.<name>_resume_print`
* `button.<name>_stop_print`

### Camera

* `camera.<name>_camera` (MJPEG stream proxy)

---

## Lovelace Card

This repository also provides a **ready-to-use card**: `k1c_printer_card.js`.

### Installation

1. Copy `k1c_printer_card.js` to `/config/www/`.
2. Add it to Lovelace resources:

```yaml
resources:
  - url: /local/k1c_printer_card.js
    type: module
```

3. Add the card in the dashboard (YAML or UI). Example:

```yaml
type: custom:k1c-printer-card
name: "Voron 2.4"  # your chosen printer name
camera: camera.voron_camera
status: sensor.voron_print_status
progress: sensor.voron_print_progress
time_left: sensor.voron_print_time_left
nozzle: sensor.voron_nozzle_temperature
bed: sensor.voron_bed_temperature
box: sensor.voron_box_temperature
layer: sensor.voron_working_layer
total_layers: sensor.voron_total_layers
light: switch.voron_light
pause_btn: button.voron_pause_print
resume_btn: button.voron_resume_print
stop_btn: button.voron_stop_print
```

### Card Features

* Progress ring with dynamic color/status
* Pause, Resume, Stop chips (context-sensitive)
* Light toggle chip
* Temperature, layer, and time chips

The card **uses the friendly name you configured** (e.g. `Voron 2.4`) instead of a hardcoded `K1C`.

---

## Services

Custom services are defined in [`services.yaml`](./custom_components/ha_creality_ws/services.yaml).
These map to printer WebSocket commands (e.g., G-code passthrough, setpoints). See service descriptions in Home Assistant Developer Tools → Services.

---

## Development

* Python files under `custom_components/ha_creality_ws/` implement entities, coordinator, and WebSocket client.
* `manifest.json` defines the integration (`ha_creality_ws`).
* The integration is designed for **local push updates** via printer WebSocket.
* Supports multiple printers (each config entry is independent).

---

## Troubleshooting

* If the camera does not display, check that your printer’s IP is accessible and that MJPEG streaming is enabled.
* If entities are missing, check **Logs → Core → DEBUG** for `custom_components.ha_creality_ws`.
* Ensure your Home Assistant version supports the unit constants (`UnitOfTemperature`, etc.). Older versions fallback automatically.

---

## License

MIT License. See [LICENSE](LICENSE) for details.

---

Do you want me to also update the **Lovelace card editor schema** so that the `name` field is clearly exposed as a **required field** (instead of optional), to better support multi-printer setups?
