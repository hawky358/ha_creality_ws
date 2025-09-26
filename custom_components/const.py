DOMAIN = "ha_creality_ws"

CONF_HOST = "host"
CONF_NAME = "name"
CONF_DISCOVERY_SCAN_CIDR = "scan_cidr"

# More generic default name
DEFAULT_NAME = "Creality Printer (WS)"

WS_PORT = 9999
MJPEG_PORT = 8080
HTTP_PORT = 80

WS_URL_TEMPLATE = "ws://{host}:" + str(WS_PORT)
MJPEG_URL_TEMPLATE = "http://{host}:" + str(MJPEG_PORT) + "/?action=stream"

# Defaults; real values are taken from telemetry when available
MFR = "Creality"
MODEL = "K1C"

# ---- Health / reconnect / keepalive (used by ws_client + coordinator + __init__) ----
STALE_AFTER_SECS = 30          # mark entities unavailable if no frames for this long
RETRY_MIN_BACKOFF = 1.0        # initial reconnect backoff (s)
RETRY_MAX_BACKOFF = 30.0       # max reconnect backoff (s)
HEARTBEAT_SECS = 10.0          # WS ping cadence (we also ack printer's JSON heartbeat with "ok")
PROBE_ON_SILENCE_SECS = 10.0   # send a benign "get" soon after connect if silent