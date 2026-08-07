"""BOM 文本解析：把剪贴板/CSV 粘贴的 BOM 转成结构化的行。

支持从立创 EDA / Excel 导出的常见列名（自动识别）。
"""

import csv
import io
import re

# 常见列名 → 内部字段（表头做小写去空格后匹配）
_COLUMN_ALIASES: dict[str, list[str]] = {
    "value": ["value", "comment", "规格", "值", "数值", "spec", "额定值", "额定参数"],
    "package": ["footprint", "package", "封装", "尺寸", "封装尺寸"],
    "quantity": ["quantity", "qty", "数量", "用量", "个数"],
    "mpn": [
        "manufacturerpart",
        "mpn",
        "厂商料号",
        "料号",
        "型号",
        "partnumber",
        "厂家型号",
        "part",
    ],
    "manufacturer": ["manufacturer", "厂商", "品牌", "厂家"],
    "designator": ["designator", "ref", "reference", "位号", "标号", "designators", "reference"],
    "supplier_part": ["supplierpart", "lcsc", "立创", "立创编号", "商品编号", "编码", "sku"],
}

# 容差后缀（如 "10k 1%"、"100nF ±5%"、孤立容差字母）
# 注意：容差字母（F/J/G/K/M/B）必须是数值后紧跟的字母，
# 避免把 "100nF" 的单位 F（法拉）误判为容差 1%。
_TOLERANCE_RE = re.compile(r"(±?\d+(?:\.\d+)?%|(?<=\d)[FJGKMB])\s*$")


def split_tolerance(text: str) -> tuple[str, str]:
    """从 "10k 1%" 拆出 (数值, 容差)；无容差返回 (原文本, "")。"""
    match = _TOLERANCE_RE.search(text or "")
    if match:
        return (text[: match.start()].strip(), match.group(1))
    return (text or "").strip(), ""


def infer_category_from_unit(unit: str) -> str | None:
    """按单位推断元件类别；无法推断返回 None"""
    if unit == "F":
        return "电容"
    if unit == "H":
        return "电感"
    if unit == "Ω":
        return "电阻"
    return None


def _norm_header(header: str) -> str:
    return header.strip().lower().replace(" ", "").replace("-", "")


def _detect_delimiter(text: str) -> str:
    first_line = text.splitlines()[0] if text else ""
    if first_line.count("\t") > first_line.count(","):
        return "\t"
    return ","


def parse_bom_text(text: str) -> list[dict]:
    """解析 BOM 文本 → 行 dict 列表（key 为内部字段名）"""
    text = (text or "").strip()
    if not text:
        return []
    delimiter = _detect_delimiter(text)
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)

    header_map: dict[str, str] = {}
    for field in reader.fieldnames or []:
        normalized = _norm_header(field)
        for internal, aliases in _COLUMN_ALIASES.items():
            if normalized in aliases or normalized == internal:
                header_map[field] = internal
                break

    rows: list[dict] = []
    for raw in reader:
        row: dict[str, str] = {}
        for original_col, internal in header_map.items():
            row[internal] = (raw.get(original_col) or "").strip()
        if any(row.values()):
            rows.append(row)
    return rows
