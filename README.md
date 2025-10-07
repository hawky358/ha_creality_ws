# Creality WebSocket Integration for Home Assistant

This custom [Home Assistant](https://www.home-assistant.io/) integration provides **native, low-latency WebSocket control and telemetry** for Creality K-series and compatible 3D printers. It exposes live state, sensors, controls, and a camera stream. A **standalone Lovelace card** (no external card dependencies) is included.

---

## Features

* **Direct WebSocket** connection (local, no cloud).
* **Push updates**; no polling.
* **States:** `idle`, `printing`, `paused`, `stopped`, `completed`, `error`, `self-testing`.
* **Optional power switch binding** to a `switch` entity for accurate “Off” handling.
* **Entities:** status, progress, time left, temperatures (nozzle/bed/chamber), current layer/total layers, etc.
* **Controls:** pause, resume, stop, light toggle.
* **Camera proxy** (MJPEG) via Home Assistant.
* **Lovelace card**: dependency-free, uses HA fonts, progress ring, contextual chips, telemetry pills.

---

## Installation

### HACS (recommended)

1. Add this repo as a [custom repository](https://hacs.xyz/docs/faq/custom_repositories/) (type: **Integration**).
2. Install **Creality WebSocket Integration**.
3. **Restart** Home Assistant.

### Manual

1. Copy `custom_components/ha_creality_ws` into `<config>/custom_components/`.
2. **Restart** Home Assistant.

---

## Configuration

### 1) Add the integration (UI)

1. **Settings → Devices & Services → Add Integration**
   Select **Creality WebSocket Integration**.
2. Enter printer hostname/IP and a friendly name.
3. Zeroconf discovery is supported; if mDNS works on your network, it will appear automatically.

### 2) Optional: bind a power switch

If your printer power is controlled by a smart plug/switch, bind it so the integration can assert `off` and zero the sensors.

* **Settings → Devices & Services →** your printer **→ Configure**
  Choose the `switch` entity. Submit.

---

## Lovelace Card

This repository **bundles** a standalone card. The integration copies the file to `/config/www/ha_creality_ws/k_printer_card.js` on setup and **auto-registers** the Lovelace resource **in storage mode**.

### Card screenshots

Below are example screenshots of the card interface states:

Idle

![Idle](img/k1c_idle.png)

Off

![Off](img/k1c_off.png)

Printing

![Printing](img/k1c_printing.png)

Processing

![Processing](img/k1c_processing.png)

### Resource registration

* **Storage mode (default)**
  The integration registers the resource automatically:

  ```
  /local/ha_creality_ws/k_printer_card.js   (type: module)
  ```

  If you ever remove/re-add the integration or migrate dashboards, verify it under:
  **Settings → Dashboards → ⋮ → Resources**.

* **YAML mode**
  Add this to your configuration:

  ```yaml
  lovelace:
    resources:
      - url: /local/ha_creality_ws/k_printer_card.js
        type: module
  ```

  (Make sure the file exists at `<config>/www/ha_creality_ws/k_printer_card.js`. The integration deploys it; if it’s missing, restart HA once.)

### Forcing Storage mode (if you previously used YAML)

If you want to switch to storage mode explicitly:

```yaml
# configuration.yaml
lovelace:
  mode: storage
```

Restart HA after changing this.

### **Hard refresh is required after first install/update**

Lovelace caches frontend resources aggressively. After installing/updating the card or integration:

* Desktop: **Ctrl+F5** (Windows/Linux), **⌘+Shift+R** (macOS)
* Mobile app: **App Settings → Reload resources** or force close + reopen.

If you still see stale UI, append a cache-buster query once:

```
/local/ha_creality_ws/k_printer_card.js?v=1
```

Then remove the `?v=` the next time.

---

## Card Usage

The card’s element tag is **`custom:k-printer-card`**.

Add via UI (Manual card) or YAML:

```yaml
type: custom:k-printer-card
name: "K1C Printer"
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

**Behavior:**

* Header icon color + conic progress ring reflect state and progress.
* Chips:

  * **Pause** shown when `printing|resuming|pausing`.
  * **Resume** shown when `paused`.
  * **Stop** shown when `printing|paused|self-testing`.
  * **Light** toggles the configured `switch`/`light` entity.
* Tapping the header opens **more-info** for `camera` (fallbacks: `status`, `progress`).

---

## Troubleshooting

* **“Configuration error” in picker or blank card**
  Hard refresh Lovelace. Verify the resource exists (see *Resource registration*). Ensure the element type is `custom:k-printer-card` (not the previous tag).
* **Controls do nothing**
  Confirm the `pause_btn`, `resume_btn`, `stop_btn` entities exist and are `button.*`. The card calls `button.press`.
  Confirm the light entity domain is `switch` or `light`.
* **Wrong states when powered off**
  Set the **Power Switch** in the integration’s Configure dialog.
* **Resource missing in storage mode**
  Remove + re-add the integration or add the resource manually under **Dashboards → Resources** pointing to `/local/ha_creality_ws/k_printer_card.js`.

---

## Status / Testing

Currently verified on **Creality K1C**. Other K-series models may work but are unverified.

---

## License

MIT. See `LICENSE`.
