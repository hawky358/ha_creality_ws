import pytest

from custom_components.ha_creality_ws.utils import (
    coerce_numbers,
    parse_model_version,
    parse_position,
    safe_float,
    extract_host_from_zeroconf,
)


def test_coerce_numbers_basic():
    d = {"a": "1", "b": "2.5", "c": "x", "d": 3}
    out = coerce_numbers(d)
    assert out["a"] == 1
    assert out["b"] == 2.5
    assert out["c"] == "x"
    assert out["d"] == 3


def test_parse_model_version_variants():
    s = "printer hw ver:ABC;printer sw ver:1.2.3;DWIN hw ver:XYZ;DWIN sw ver:9.9;"
    hw, sw = parse_model_version(s)
    assert hw == "ABC"
    assert sw == "1.2.3"

    s2 = "DWIN hw ver:XYZ;DWIN sw ver:9.9;"
    hw2, sw2 = parse_model_version(s2)
    assert hw2 == "DWIN XYZ"
    assert sw2 == "DWIN 9.9"


def test_parse_position_ok_and_bad():
    d = {"curPosition": "X:12.3 Y:4.5 Z:-6"}
    x, y, z = parse_position(d)
    assert (x, y, z) == (12.3, 4.5, -6.0)

    d2 = {"curPosition": "invalid"}
    assert parse_position(d2) == (None, None, None)


def test_safe_float():
    assert safe_float("3.14") == 3.14
    assert safe_float(None) is None
    assert safe_float("abc") is None


def test_extract_host_from_zeroconf_dict_and_obj():
    info = {"host": "1.2.3.4"}
    assert extract_host_from_zeroconf(info) == "1.2.3.4"

    class Dummy:
        ip_addresses = ["5.6.7.8", "::1"]
    assert extract_host_from_zeroconf(Dummy()) == "5.6.7.8"
