"""参数解析器单元测试：覆盖各种真实厂商/人类写法"""

import pytest

from app.parsers.bom import split_tolerance
from app.parsers.canonical import (
    build_canonical_key,
    compute_canonical_key,
    normalize_dielectric,
    normalize_package,
    normalize_tolerance,
)
from app.parsers.smd import parse_smd_code
from app.parsers.values import parse_number, parse_value


# --- values: 数值与单位 ---
@pytest.mark.parametrize(
    ("text", "value", "unit"),
    [
        ("10k", 10_000.0, ""),
        ("10kΩ", 10_000.0, "Ω"),
        ("10KΩ", 10_000.0, "Ω"),
        ("1kohm", 1_000.0, "Ω"),
        ("10 欧", 10.0, "Ω"),
        ("100nF", 1e-7, "F"),
        ("4.7uF", 4.7e-6, "F"),
        ("470u", 470e-6, ""),
        ("1M", 1e6, ""),
        ("330", 330.0, ""),
        ("100V", 100.0, "V"),
        ("0", 0.0, ""),
    ],
)
def test_parse_value(text: str, value: float, unit: str) -> None:
    result = parse_value(text)
    assert result is not None
    assert result.value == pytest.approx(value)
    assert result.unit == unit


@pytest.mark.parametrize(
    "text",
    ["", "  ", "abc", "10%", "1.2.3", "±", "kΩ"],
)
def test_parse_value_invalid(text: str) -> None:
    assert parse_value(text) is None


@pytest.mark.parametrize("text", ["100nf", "0.1uf"])
def test_parse_value_lowercase_unit(text: str) -> None:
    """小写单位也应解析并归一化为大写（100nf → F）"""
    result = parse_value(text)
    assert result is not None, text
    assert result.value == pytest.approx(1e-07)
    assert result.unit == "F"


def test_split_tolerance_keeps_unit_letter() -> None:
    """100nF 的 F 是法拉单位，不能被当成容差字母拆掉（回归）"""
    value, tolerance = split_tolerance("100nF")
    assert value == "100nF"
    assert tolerance == ""
    # 真正的容差照常拆分
    value, tolerance = split_tolerance("104J")
    assert value == "104"
    assert tolerance == "J"


@pytest.mark.parametrize(
    ("token", "expected"),
    [
        ("2R2", 2.2),
        ("1R0", 1.0),
        ("0R1", 0.1),
        ("3k3", 3_300.0),  # 电阻标号里 K 也可表示小数位（3k3 = 3.3k）
    ],
)
def test_parse_number_r_as_decimal(token: str, expected: float) -> None:
    # R/r 作小数点；但 "3k3" 里 k 不是小数位，需按常规后缀处理
    result = parse_number(token)
    assert result is not None
    assert result == pytest.approx(expected)


# --- smd: 贴片标号 ---
@pytest.mark.parametrize(
    ("code", "category", "expected"),
    [
        ("103", "电阻", 10_000.0),
        ("1002", "电阻", 10_000.0),
        ("471", "电阻", 470.0),
        ("104", "电容", 1e-7),  # 100nF
        ("105", "电容", 1e-6),  # 1uF
        ("0", "电阻", 0.0),
        ("000", "电容", 0.0),
    ],
)
def test_parse_smd_code(code: str, category: str, expected: float) -> None:
    assert parse_smd_code(code, category) == pytest.approx(expected)


@pytest.mark.parametrize(
    ("code", "category"),
    [("47", "电阻"), ("5R1", "电阻"), ("abc", "电容"), ("12", "电容")],
)
def test_parse_smd_code_invalid(code: str, category: str) -> None:
    assert parse_smd_code(code, category) is None


# --- canonical: 容差/封装/介质归一化 ---
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("F", "1%"),
        ("J", "5%"),
        ("K", "10%"),
        ("±5%", "5%"),
        ("5%", "5%"),
        ("10", "10%"),
        (None, None),
    ],
)
def test_normalize_tolerance(text: str | None, expected: str | None) -> None:
    assert normalize_tolerance(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [(" 0603 ", "0603"), ("SMD-0805", "smd-0805"), (None, None)],
)
def test_normalize_package(text: str | None, expected: str | None) -> None:
    assert normalize_package(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [("x7r", "X7R"), ("c0g", "C0G"), (None, None)],
)
def test_normalize_dielectric(text: str | None, expected: str | None) -> None:
    assert normalize_dielectric(text) == expected


# --- canonical: 等效键 ---
def test_resistor_equivalent_key() -> None:
    # 不同厂商、不同写法，等效键应一致
    k1 = compute_canonical_key("电阻", 10_000.0, "Ω", "0603", "1%")
    k2 = compute_canonical_key("电阻", 10_000.0, "Ω", "0603", "F")
    assert k1 == k2 == "R|10000|0603|1%"


def test_capacitor_key() -> None:
    # 100nF == 0.1uF == 104
    k1 = compute_canonical_key("电容", 1e-7, "F", "0805", None, 50, "X7R")
    k2 = compute_canonical_key("电容", 1e-7, "F", "0805", None, 50, "x7r")
    assert k1 == k2 == "C|1e-07|0805|50|X7R"


def test_inductor_key() -> None:
    assert compute_canonical_key("电感", 4.7e-6, "H", "0805") == "L|4.7e-06|0805"


def test_ic_uses_exact_mpn() -> None:
    k = build_canonical_key("IC", "stm32f103c8t6", None, "", None, None)
    assert k == "X|STM32F103C8T6"
