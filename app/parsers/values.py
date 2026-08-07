"""数值与单位解析：把人类/厂商写法归一成结构化数值。

支持的真实写法示例：
    10k / 10kΩ / 100nF / 4.7uF / 2R2 / 330 / 1M / 100V / 470u
"""

import re
from dataclasses import dataclass

# 数值后缀 → 倍数（k/K 都支持，µ/μ 兼容）
_PREFIX: dict[str, float] = {
    "T": 1e12,
    "G": 1e9,
    "M": 1e6,
    "k": 1e3,
    "K": 1e3,
    "m": 1e-3,
    "u": 1e-6,
    "µ": 1e-6,
    "μ": 1e-6,
    "n": 1e-9,
    "p": 1e-12,
    "f": 1e-15,
}

# 尾部单位符号（贪婪匹配，Ω/ohm/欧姆 等文本形式兼容）
_UNIT_RE = re.compile(r"(Ω|Ohm|OHM|ohm|欧姆|欧|F|H|V|A|W|Hz)\s*$")

# 数值部分：数字 + 可选后缀字母 + 可选小数位（3k3 = 3.3k）
_NUM_TOKEN_RE = re.compile(r"^(\d+(?:\.\d+)?)([TGMkKmµμunpf]?)(\d*)$")

_UNIT_NORMALIZE = {
    "Ohm": "Ω",
    "OHM": "Ω",
    "ohm": "Ω",
    "欧姆": "Ω",
    "欧": "Ω",
}


@dataclass(frozen=True)
class ParsedValue:
    """解析结果：数值已换算到 base 单位（如 10kΩ → 10000.0）"""

    value: float
    unit: str  # 标准单位符号（Ω/F/H/V/A...），未知为 ""
    raw: str  # 原始输入（去空格后）


def parse_value(text: str) -> ParsedValue | None:
    """解析单个数值字段；无法解析（空、纯字母、含 % 等）返回 None。

    会把数值后缀与单位前缀都换算掉：
        "100nF"  → ParsedValue(1e-7, "F")
        "10kΩ"   → ParsedValue(10000.0, "Ω")
        "2R2"    → ParsedValue(2.2, "")
        "330"    → ParsedValue(330.0, "")
    """
    if not text or not text.strip():
        return None
    raw = text.strip().replace(" ", "").replace(",", "").replace("±", "")
    # 分离尾部单位
    unit = ""
    num_part = raw
    m = _UNIT_RE.search(raw)
    if m:
        unit = m.group(1)
        num_part = raw[: m.start()]
    if not num_part:
        return None
    value = parse_number(num_part)
    if value is None:
        return None
    return ParsedValue(value=value, unit=_UNIT_NORMALIZE.get(unit, unit), raw=raw)


def parse_number(token: str) -> float | None:
    """解析数值部分（含后缀）。

    支持：
        R/r 作小数点：2R2 → 2.2
        单位字母作小数点：3k3 → 3300，1u5 → 1.5e-6，6M8 → 6.8e6
        普通后缀：10k → 10000，100n → 1e-7
    """
    t = token.strip().replace(" ", "")
    if not t:
        return None
    # R/r 作为小数点：2R2 → 2.2，1R0 → 1.0
    if "R" in t or "r" in t:
        t = t.replace("R", ".").replace("r", ".")
        try:
            return float(t)
        except ValueError:
            return None
    m = _NUM_TOKEN_RE.match(t)
    if not m:
        return None
    mantissa = m.group(1)
    suffix = m.group(2)
    frac = m.group(3)
    if frac and "." not in mantissa:
        # 单位字母作小数点：3k3 → 3.3k，1u5 → 1.5e-6
        number = float(f"{mantissa}.{frac}")
    else:
        number = float(mantissa)
    mult = _PREFIX.get(suffix, 1.0) if suffix else 1.0
    return number * mult
