"""等效类（canonical key）计算。

不同厂商料号但电气等效的元件（如多家供应商的 10kΩ 0603 1% 电阻）
归入同一等效键，库存匹配就按等效键聚合。
"""

import re

# 容差字母标号 → 百分比（IEC 62 惯例）
_TOLERANCE_LETTER: dict[str, str] = {
    "B": "0.1%",
    "D": "0.5%",
    "F": "1%",
    "G": "2%",
    "J": "5%",
    "K": "10%",
    "M": "20%",
}


def normalize_tolerance(text: str | None) -> str | None:
    """容差归一化：F→1%，±5%→5%，5%→5%，J→5%。"""
    if not text:
        return None
    t = text.strip().upper().replace("±", "").replace(" ", "")
    if not t:
        return None
    if t in _TOLERANCE_LETTER:
        return _TOLERANCE_LETTER[t]
    if t.endswith("%"):
        t = t[:-1]
    try:
        return f"{float(t):g}%"
    except ValueError:
        return None


_PKG_SOT_RE = re.compile(r"sot-\d+")


def normalize_package(text: str | None) -> str | None:
    """封装归一化：小写、去空格，并统一常见写法。

    处理立创 EDA 封装名差异：
        C0603 / R0603 → 0603
        SOT-23-3_L2.9-W1.3-P1.90-LS2.4-BR → SOT-23（取下划线前主名 + SOT 系列）
        CAP-TH_BD5.0-P2.00-D0.5-FD / *_TH_* → 插件
    """
    if not text:
        return None
    t = text.strip().lower().replace(" ", "")
    # 立创封装常带尺寸段（xxx_L2.9-W1.3...），先取下划线前主名
    t = t.split("_")[0]
    # 剥离 C/R 前缀：C0603 / R0603 → 0603
    t = re.sub(r"^[cr](\d)", r"\1", t)
    # TH 直插（cap-th / res-th / *_th）→ 插件
    if "-th" in t:
        return "插件"
    # SOT 系列统一为 SOT-x（SOT-23-3 → SOT-23，SOT-223 → SOT-223）
    m = _PKG_SOT_RE.search(t)
    if m:
        return m.group(0)
    return t


def normalize_dielectric(text: str | None) -> str | None:
    """电容介质归一化：转大写（x7r → X7R）。"""
    if not text:
        return None
    return text.strip().upper().replace(" ", "")


def _fmt(value: float | None) -> str:
    """数值格式化为规范字符串（同值必同串，避免 0.00047 vs 4.7e-04 分裂）。

    整数 → 整数形式；其余 → 统一科学计数（6 位有效数字，去尾零）。
    """
    if value is None:
        return ""
    v = float(value)
    if v.is_integer():
        return str(int(v))
    mantissa, exp = f"{v:.5e}".split("e")
    mantissa = mantissa.rstrip("0").rstrip(".")
    return f"{mantissa}e{exp}"


def compute_canonical_key(
    category: str,
    value: float | None,
    unit: str,
    package: str | None,
    tolerance: str | None = None,
    voltage: float | None = None,
    dielectric: str | None = None,
) -> str:
    """按类别计算等效键。

    电阻 = 值 + 封装 + 容差
    电容 = 值 + 封装 + 耐压 + 介质
    电感 = 值 + 封装
    其他（IC 等）= "X|" 占位，由调用方拼接精确型号
    """
    if "电阻" in category:
        return "R|{}|{}|{}".format(
            _fmt(value),
            normalize_package(package) or "",
            normalize_tolerance(tolerance) or "",
        )
    if "电容" in category:
        return "C|{}|{}|{}|{}".format(
            _fmt(value),
            normalize_package(package) or "",
            _fmt(voltage),
            normalize_dielectric(dielectric) or "",
        )
    if "电感" in category:
        return "L|{}|{}".format(_fmt(value), normalize_package(package) or "")
    return "X|"


def build_canonical_key(
    category: str,
    mpn: str,
    value: float | None,
    unit: str,
    package: str | None,
    tolerance: str | None,
    voltage: float | None = None,
    dielectric: str | None = None,
) -> str:
    """完整等效键：精确类别（IC 等）回退到料号大写。"""
    key = compute_canonical_key(category, value, unit, package, tolerance, voltage, dielectric)
    if key == "X|":
        return f"X|{mpn.strip().upper()}"
    return key
