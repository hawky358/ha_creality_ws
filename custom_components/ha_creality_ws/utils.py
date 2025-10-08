from __future__ import annotations

import re
from typing import Any, Optional

__all__ = [
    "coerce_numbers",
    "parse_model_version",
    "parse_position",
    "safe_float",
    "extract_host_from_zeroconf",
]


def coerce_numbers(d: dict[str, Any]) -> dict[str, Any]:
    """Convert numeric strings in a dict to numbers where safe."""
    out: dict[str, Any] = {}
    for k, v in d.items():
        if isinstance(v, str):
            try:
                out[k] = float(v) if "." in v else int(v)
                continue
            except Exception:
                pass
        out[k] = v
    return out


def parse_model_version(s: str | None) -> tuple[str | None, str | None]:
    """Extract HW/SW versions from a semi-structured string (Creality format)."""
    if not s or not isinstance(s, str):
        return (None, None)

    parts: dict[str, Optional[str]] = {}
    for seg in s.split(";"):
        seg = seg.strip()
        if not seg or ":" not in seg:
            continue
        k, v = seg.split(":", 1)
        parts[k.strip().lower()] = (v.strip() or None)

    hw = parts.get("printer hw ver") or parts.get("dwin hw ver")
    sw = parts.get("printer sw ver") or parts.get("dwin sw ver")
    if hw and hw == parts.get("dwin hw ver"):
        hw = f"DWIN {hw}"
    if sw and sw == parts.get("dwin sw ver"):
        sw = f"DWIN {sw}"
    return (hw, sw)


_POS_RE = re.compile(r"X:(?P<X>-?\d+(?:\.\d+)?)\s+Y:(?P<Y>-?\d+(?:\.\d+)?)\s+Z:(?P<Z>-?\d+(?:\.\d+)?)")


def parse_position(d: dict[str, Any]) -> tuple[float | None, float | None, float | None]:
    raw = d.get("curPosition")
    if not isinstance(raw, str):
        return (None, None, None)
    m = _POS_RE.search(raw)
    if not m:
        return (None, None, None)
    try:
        return (float(m.group("X")), float(m.group("Y")), float(m.group("Z")))
    except Exception:
        return (None, None, None)


def safe_float(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def extract_host_from_zeroconf(info: Any) -> Optional[str]:
    """Extract a host/IP from zeroconf discovery info supporting dict or object styles."""
    if isinstance(info, dict):
        host = info.get("host")
        if host:
            return str(host)
        addrs = info.get("addresses") or info.get("ip_addresses") or info.get("ip_address")
        if isinstance(addrs, (list, tuple)) and addrs:
            return str(addrs[0])
        if isinstance(addrs, str):
            return addrs
        hn = info.get("hostname")
        if isinstance(hn, str):
            return hn.strip(".")
        return None
    try:
        addrs: list[str] = []
        if hasattr(info, "ip_addresses") and info.ip_addresses:
            addrs = [str(a) for a in info.ip_addresses]
        elif hasattr(info, "addresses") and info.addresses:
            addrs = [str(a) for a in info.addresses]
        if addrs:
            v4 = next((a for a in addrs if ":" not in a), None)
            return v4 or addrs[0]
        if getattr(info, "host", None):
            return str(info.host)
        if getattr(info, "hostname", None):
            return str(info.hostname).rstrip(".")
    except Exception:
        pass
    return None
