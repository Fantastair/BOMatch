"""EIA 贴片元件标号解析。

贴片电阻/电容常用三位或四位标号：
    103   → 10 × 10^3 = 10kΩ（电阻） / 10nF（电容，pF 为底）
    1002  → 100 × 10^2 = 10kΩ
    471   → 47 × 10^1 = 470Ω
    0/000 → 跳线（0Ω）
"""


def parse_smd_code(code: str, category: str) -> float | None:
    """解析贴片标号，返回 base 单位数值；不是标号返回 None。

    电阻 → Ω；电容 → F（标号以 pF 为底）。
    """
    t = code.strip()
    if not t.isdigit():
        return None
    if len(t) == 1:
        return 0.0 if t == "0" else None
    if set(t) == {"0"}:
        return 0.0
    if len(t) == 3:
        mantissa, exp = t[:2], int(t[2])
    elif len(t) == 4:
        mantissa, exp = t[:3], int(t[3])
    else:
        return None
    value = int(mantissa) * (10**exp)
    if "电容" in category:
        return value * 1e-12  # pF → F
    return float(value)  # 电阻（及默认）→ Ω
