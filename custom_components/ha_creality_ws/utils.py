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

    # Try printer versions first, then DWIN versions as fallback
    hw = parts.get("printer hw ver")
    sw = parts.get("printer sw ver")
    
    # If printer versions are empty or just whitespace, use DWIN versions (prefixed with "DWIN")
    if not hw or hw.strip() == "":
        hw = parts.get("dwin hw ver")
        if hw:
            hw = f"DWIN {hw}"
    
    if not sw or sw.strip() == "":
        sw = parts.get("dwin sw ver")
        if sw:
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

class ModelDetection:
    """Detect printer model and capabilities from telemetry data."""
    
    def __init__(self, coord_data):
        self.model = (coord_data or {}).get("model") or ""
        self.model_l = str(self.model).lower()
        # Note: modelVersion could be used for more reliable detection
        # but requires known model/mainboard version mapping
        
        # Individual printer model detection
        # K1 Base - "CR-K1"
        self.is_k1_base = "cr-k1" in self.model_l
        
        # K1 SE - "K1 SE"
        self.is_k1_se = "k1 se" in self.model_l
        
        # K1 Max - "CR-K1 Max"
        self.is_k1_max = "cr-k1 max" in self.model_l
        
        # K2 Base - "F021"
        self.is_k2_base = "F021" in self.model
        
        # K2 Pro - "F012"
        self.is_k2_pro = "F012" in self.model
        
        # K2 Plus - "F008"
        self.is_k2_plus = "F008" in self.model
        
        # Ender-3 V3 KE - "F005"
        self.is_ender_v3_ke = (
            "F005" in self.model or
            "ender-3 v3 ke" in self.model_l
        )
        
        # Ender-3 V3 Plus - "F002"
        self.is_ender_v3_plus = (
            "F002" in self.model or
            "ender-3 v3 plus" in self.model_l
        )
        
        # Ender-3 V3 - "F001"
        # Must be exactly "ender-3 v3" (not KE, Plus, or SE)
        # Check that it's not one of the variants first
        is_not_variant = not (
            self.is_ender_v3_ke or 
            self.is_ender_v3_plus
        )
        self.is_ender_v3 = (
            is_not_variant and (
                "F001" in self.model or
                "ender-3 v3" in self.model_l
            )
        )
        
        # Creality Hi - "F018"
        self.is_creality_hi = (
            "F018" in self.model or
            "hi" in self.model_l
        )
        
        # Family groupings
        # K1 Family
        self.is_k1_family = (
            self.is_k1_base or
            self.is_k1_se or
            self.is_k1_max or
            "k1" in self.model_l
        )
        
        # K2 Family
        self.is_k2_family = (
            self.is_k2_base or
            self.is_k2_pro or
            self.is_k2_plus or
            "k2" in self.model_l
        )
        
        # Ender-3 V3 Family
        self.is_ender_v3_family = (
            self.is_ender_v3_ke or
            self.is_ender_v3_plus or
            self.is_ender_v3 or
            ("ender" in self.model_l and "v3" in self.model_l)
        )
        
        # Feature detection
        self.has_box_control = self.is_k2_pro or self.is_k2_plus
        self.has_box_sensor = (self.is_k1_family and not self.is_k1_se) or self.is_k1_max or self.is_k2_family
        self.has_light = not (self.is_k1_se or self.is_ender_v3_family)
        
        self.friendly_name = self.get_friendly_name() or self.model
        
    def get_friendly_name(self):
        
        if self.is_k1_base:
            return "K1"
        if self.is_k1_se:
            return "K1 SE"
        if self.is_k1_max:
            return "K1 Max"
        if self.is_k2_base:
            return "K2"
        if self.is_k2_pro:
            return "K2 Pro"
        if self.is_k2_plus:
            return "K2 Plus"
        if self.is_ender_v3_ke:
            return "Ender-3 V3 KE"
        if self.is_ender_v3_plus:
            return "Ender-3 V3 Plus"
        if self.is_ender_v3:
            return "Ender-3 V3"
        if self.is_creality_hi:
            return "Creality Hi"
        
        return None
