# Creality WebSocket Integration for Home Assistant

This custom [Home Assistant](https://www.home-assistant.io/) integration provides **native, low-latency WebSocket control and telemetry** for Creality K-series and compatible 3D printers. It exposes the printer’s live state, sensors, controls, and camera stream to Home Assistant and includes a ready-to-use Lovelace card for printer monitoring.

---

## Features

*   **Direct WebSocket connection** to the printer, no cloud required.
*   **Local push updates** (no polling).
*   **Rich Status Reporting**: Provides detailed printer states like `Idle`, `Printing`, `Paused`, `Stopped`, `Completed`, `Error`, and even `Self-Testing`.
*   **Optional Power Switch Integration**: Can monitor a separate `switch` entity (like a smart plug) to accurately determine the printer's `Off` state and reset all sensors to zero.
*   **Comprehensive Entities**:
    *   Status, progress, job time, layers, object count
    *   Temperatures (bed, nozzle, chamber)
    *   Speeds, flow rate, fans
    *   Current position (X/Y/Z)
    *   Current object / excluded objects
*   **Controls**:
    *   Pause, Resume, Stop print (Stop is available during calibration)
    *   Light toggle
    *   Speed/flow tuning
    *   Temperature and fan setpoints
*   **MJPEG camera proxy** with relay via Home Assistant.
*   **Custom Lovelace card** (`k1c_printer_card.js`) with context-aware controls, temperatures, progress ring, and printer info.

---

## Status / Testing

⚠️ This integration has been **tested only on Creality K1C**.
It may work on other **Creality Klipper-based printers with the stock web interface**, but this is unverified.

👉 **Looking for testers!**
If you own another supported model (e.g. K1, K1 Max), please install this integration and report results by opening an issue or PR on GitHub.

---

## Installation

### HACS (recommended)

1.  Add this repository as a [custom repository](https://hacs.xyz/docs/faq/custom_repositories/) in HACS (`Integration` type).
2.  Install **Creality WebSocket Integration**.
3.  Restart Home Assistant.

### Manual

1.  Copy the `custom_components/ha_creality_ws` directory to `<config>/custom_components/`.
2.  Restart Home Assistant.

---

## Configuration

### 1. Add the Integration

This integration uses a **config flow** (UI setup).

1.  Navigate to **Settings → Devices & Services → Add Integration**.
2.  Search for **Creality WebSocket Integration**.
3.  Enter your printer’s hostname or IP and give it a friendly name.

Zeroconf discovery is supported; the printer should appear automatically if mDNS is working on your network.

### 2. Configure the Power Switch (Optional)

To enable the `Off` state and have sensors zero-out when the printer is powered down, you must link the integration to a power monitoring switch (e.g., a smart plug).

1.  Navigate to **Settings → Devices & Services**.
2.  Find your Creality printer integration and click **Configure**.
3.  Use the dropdown menu to select the `switch` entity that controls your printer's power.
4.  Click **Submit**. The integration will now use this switch as the source of truth for its power state.

---

## Lovelace Card

This repository includes a **ready-to-use card**: `k1c_printer_card.js`.

### Installation

The integration **automatically** copies the `k1c_printer_card.js` file to the correct location (`/config/www/ha_creality_ws/k1c_printer_card.js`). You only need to add it to your Lovelace resources.

1.  Navigate to **Settings → Dashboards**.
2.  Click the three-dots menu at the top right and select **Resources**.
3.  Click **Add Resource**.
4.  Enter the URL: `/local/ha_creality_ws/k1c_printer_card.js` and select **JavaScript Module** as the type.

### Card Usage

Add the card to your dashboard using the UI or YAML.

```yaml
type: custom:k1c-printer-card
name: "K1C Printer"  # This name will appear on the card
camera: camera.k1c_printer_camera
status: sensor.k1c_print_status
progress: sensor.k1c_print_progress
time_left: sensor.k1c_print_time_left
nozzle: sensor.k1c_nozzle_temperature
bed: sensor.k1c_bed_temperature
box: sensor.k1c_box_temperature
layer: sensor.k1c_working_layer
total_layers: sensor.k1c_total_layers
light: switch.k1c_light
pause_btn: button.k1c_pause_print
resume_btn: button.k1c_resume_print
stop_btn: button.k1c_stop_print
```

---

## Entities

Entities are created dynamically. The `<name>` is based on the name you provided during setup.

*   `sensor.<name>_print_status`
*   `sensor.<name>_print_progress`
*   `sensor.<name>_print_time_left`
*   ...and many more. See the integration's device page for a full list.
*   `camera.<name>_camera`

---

## Development & Troubleshooting

*   This integration is designed for **local push updates** and supports multiple printers.
*   If entities are `unavailable` or `unknown`, first check that the printer is powered on and connected to the network.
*   If the state appears incorrect, verify the **Power Switch** is set correctly in the integration's **Configure** menu.
*   For deeper issues, check **Logs** for entries related to `custom_components.ha_creality_ws`.

---

## License

MIT License. See [LICENSE](LICENSE) for details.