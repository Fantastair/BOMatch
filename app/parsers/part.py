"""料号表单字段解析：原始文本 → 结构化参数 + 等效键"""

from app.parsers.canonical import (
    build_canonical_key,
    normalize_dielectric,
    normalize_package,
    normalize_tolerance,
)
from app.parsers.smd import parse_smd_code
from app.parsers.values import parse_value


def resolve_value(value_text: str, category: str) -> tuple[float | None, str]:
    """解析数值文本 → (base 单位数值, 单位)。

    先试贴片标号（104/103），再试常规数值（10k/100nF/2R2）。
    无法解析返回 (None, "")。
    """
    text = (value_text or "").strip()
    if not text:
        return None, ""
    smd = parse_smd_code(text, category)
    if smd is not None:
        unit = "F" if "电容" in category else "Ω"
        return smd, unit
    parsed = parse_value(text)
    if parsed is not None:
        return parsed.value, parsed.unit
    return None, ""


def resolve_voltage(text: str | None) -> float | None:
    """解析耐压文本（50V / 50）→ 数值；无法解析返回 None。"""
    if not text or not text.strip():
        return None
    parsed = parse_value(text)
    return parsed.value if parsed else None


def part_canonical_key(
    category: str,
    mpn: str,
    value: float | None,
    unit: str,
    package: str | None,
    tolerance: str | None,
    voltage: float | None,
    dielectric: str | None,
) -> str:
    """按类别计算 Part 的等效键（容差/封装/介质在此归一化）。"""
    return build_canonical_key(
        category,
        mpn,
        value,
        unit,
        normalize_package(package),
        normalize_tolerance(tolerance),
        voltage,
        normalize_dielectric(dielectric),
    )
