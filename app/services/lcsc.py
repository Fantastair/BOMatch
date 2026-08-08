"""立创商城（szlcsc）价格/库存/参数查询与回填。

基于实测接口（无官方 SLA，可能变更，改动只需集中在本模块）：
- 方案A：POST https://list.szlcsc.com/substitute/simple/list?productCode=Cxxx
- 方案B：GET https://item.szlcsc.com/{productId}.html 解析 schema.org JSON-LD（兜底）
"""

import json
import re
import time
import urllib.request
from dataclasses import dataclass, field

from app.parsers.canonical import normalize_dielectric, normalize_package, normalize_tolerance
from app.parsers.part import part_canonical_key
from app.parsers.values import parse_value

# 请求间隔（秒），避免触发风控
REQUEST_INTERVAL = 0.5
_last_request_at = 0.0

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "Chrome/150.0.0.0 Safari/537.36"
)


@dataclass
class LcscProduct:
    """归一化后的立创商品信息"""

    code: str
    model: str | None = None  # 厂家型号
    brand: str | None = None  # 品牌
    package: str | None = None  # 封装
    params: dict = field(default_factory=dict)  # 原始参数表（中文键）
    tolerance: str | None = None  # 归一化容差
    voltage: float | None = None  # 额定电压（V）
    dielectric: str | None = None  # 介质
    value: float | None = None  # 数值（base 单位）
    value_unit: str = ""  # 标准单位（Ω/F/H）
    value_raw: str | None = None  # 原始数值文本（如 22uF）
    moq_price: float | None = None  # MOQ 单价
    stock: int | None = None  # 商城库存（仅参考，不写回本地）


# ---- 参数映射：立创中文参数键 → Part 字段 ----
_PARAM_KEYS: dict[str, list[str]] = {
    "tolerance": ["精度", "容差", "允许偏差", "偏差"],
    "voltage": ["额定电压", "耐压", "工作电压"],
    "dielectric": ["温度系数", "介质", "材质"],
}

# 数值参数键：容值/阻值/感值（含常见变体）
_VALUE_KEYS: list[str] = ["容值", "容量", "电容", "阻值", "电阻", "感值", "电感"]


def extract_value(params: dict | None) -> tuple[float | None, str, str | None]:
    """从立创参数表提取 (数值 base 单位, 单位, 原始文本)；取不到返回 (None, "", None)。"""
    for key, raw in (params or {}).items():
        text = str(raw or "").strip()
        if not text or text == "-":
            continue
        if any(a in key for a in _VALUE_KEYS):
            parsed = parse_value(text)
            if parsed is not None:
                return parsed.value, parsed.unit, parsed.raw
    return None, "", None


def map_params(params: dict | None) -> tuple[str | None, float | None, str | None]:
    """从立创参数表提取 (容差, 耐压, 介质)"""
    tolerance: str | None = None
    voltage: float | None = None
    dielectric: str | None = None
    for key, raw in (params or {}).items():
        value = str(raw or "").strip()
        if not value or value == "-":
            continue
        for target, aliases in _PARAM_KEYS.items():
            if key in aliases or any(a in key for a in aliases):
                if target == "tolerance" and tolerance is None:
                    tolerance = normalize_tolerance(value)
                elif target == "voltage" and voltage is None:
                    parsed = parse_value(value)
                    voltage = parsed.value if parsed else None
                elif target == "dielectric" and dielectric is None:
                    dielectric = normalize_dielectric(value)
                break
    return tolerance, voltage, dielectric


# ---- 网络请求（标准库 urllib，限速） ----
def _throttle() -> None:
    global _last_request_at
    elapsed = time.monotonic() - _last_request_at
    if elapsed < REQUEST_INTERVAL:
        time.sleep(REQUEST_INTERVAL - elapsed)
    _last_request_at = time.monotonic()


def _http_json(
    url: str, method: str = "GET", data: bytes | None = None, headers: dict | None = None
) -> dict:
    _throttle()
    req = urllib.request.Request(url, method=method, data=data, headers=headers or {})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def _http_text(url: str, headers: dict | None = None) -> str:
    _throttle()
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read().decode("utf-8", errors="replace")


# ---- 方案A：substitute 接口 ----
def _query_substitute(code: str) -> LcscProduct | None:
    url = f"https://list.szlcsc.com/substitute/simple/list?productCode={code}"
    headers = {
        "User-Agent": _UA,
        "Referer": "https://item.szlcsc.com/",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    data = _http_json(url, method="POST", data=b"{}", headers=headers)
    main = (data.get("result") or {}).get("mainProduct") or {}
    if not main:
        return None
    prices = {
        p["startPurchasedNumber"]: p.get("thePrice") or p.get("productPrice")
        for p in main.get("productPriceList") or []
    }
    params = main.get("paramLinkedMap") or {}
    tolerance, voltage, dielectric = map_params(params)
    value, value_unit, value_raw = extract_value(params)
    return LcscProduct(
        code=code,
        model=main.get("productModel"),
        brand=main.get("productGradePlateName"),
        package=main.get("encapsulationModel"),
        params=params,
        tolerance=tolerance,
        voltage=voltage,
        dielectric=dielectric,
        value=value,
        value_unit=value_unit,
        value_raw=value_raw,
        moq_price=prices[min(prices)] if prices else None,
        stock=main.get("totalStockNumber") or main.get("stockNumber"),
    )


# ---- 方案B：商品页 JSON-LD 兜底 ----
_JSONLD_RE = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)


def _walk_products(node):
    """递归遍历 JSON-LD 中的 @type == Product 节点（含 @graph 嵌套）"""
    if isinstance(node, dict):
        node_type = node.get("@type")
        if node_type == "Product" or (isinstance(node_type, list) and "Product" in node_type):
            yield node
        for value in node.values():
            yield from _walk_products(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk_products(item)


def query_by_pid(pid: str) -> LcscProduct | None:
    """方案B：商品页 JSON-LD（返回参考价与库存）"""
    url = f"https://item.szlcsc.com/{pid}.html"
    html = _http_text(url, headers={"User-Agent": _UA})
    for script in _JSONLD_RE.findall(html):
        try:
            doc = json.loads(script)
        except json.JSONDecodeError:
            continue
        for node in _walk_products(doc):
            offers = node.get("offers") or {}
            inventory = offers.get("inventoryLevel") or {}
            return LcscProduct(
                code=node.get("sku") or "",
                model=node.get("mpn"),
                brand=(node.get("brand") or {}).get("name"),
                moq_price=offers.get("price"),
                stock=inventory.get("value"),
            )
    return None


def query_product_detailed(code: str, pid: str | None = None) -> tuple[LcscProduct | None, str | None]:
    """查询立创商品并返回人类可读的错误原因。

    返回 (product, error)：
    - 成功：product 非 None，error 为 None；
    - 失败：product 为 None，error 为原因描述（供页面提示）。
    方案A（substitute 接口）失败且有 pid 时用方案B（商品页 JSON-LD）兜底。
    """
    a_error: str | None = None
    try:
        product = _query_substitute(code)
        if product is not None:
            return product, None
        a_error = "substitute 接口未返回该编号商品"
    except Exception as exc:  # noqa: BLE001
        a_error = f"substitute 接口异常：{exc}"
    if pid:
        try:
            product = query_by_pid(pid)
            if product is not None:
                return product, None
        except Exception as exc:  # noqa: BLE001
            return None, f"{a_error}；商品页兜底也失败：{exc}"
        return None, f"{a_error}；商品页兜底也未查到"
    return None, a_error


def query_product(code: str, pid: str | None = None) -> LcscProduct | None:
    """查询立创商品：优先方案A，失败且有 pid 时用方案B兜底（兼容旧调用，丢弃错误信息）。"""
    product, _ = query_product_detailed(code, pid)
    return product


# ---- 回填到 Part ----
def apply_product(part, product: LcscProduct | None) -> None:
    """把立创查询结果回填到 Part（不覆盖已有值），并重算等效键。

    注意：只修改内存中的对象，提交由调用方负责。
    """
    if product is None:
        return
    # mpn 从立创编号（C+数字）迁移到厂家型号
    if part.mpn.startswith("C") and part.mpn[1:].isdigit():
        if not part.lcsc_code:
            part.lcsc_code = part.mpn
        if product.model:
            part.mpn = product.model
    elif product.model and not part.mpn:
        part.mpn = product.model
    if product.brand and not part.manufacturer:
        part.manufacturer = product.brand
    # 封装/值：同步接口此前漏掉的两个字段，补齐后等效键才能正确匹配 BOM
    if product.package and not part.package:
        part.package = normalize_package(product.package)
    if product.value is not None and part.value is None:
        part.value = product.value
        part.value_unit = product.value_unit
        part.value_raw = product.value_raw or (
            f"{product.value:g}{product.value_unit}" if product.value_unit else f"{product.value:g}"
        )
    if product.tolerance and not part.tolerance:
        part.tolerance = product.tolerance
    if product.voltage and not part.voltage:
        part.voltage = product.voltage
    if product.dielectric and not part.dielectric:
        part.dielectric = product.dielectric
    # 参数变化后重算等效键
    part.canonical_key = part_canonical_key(
        part.category.name,
        part.mpn,
        part.value,
        part.value_unit,
        part.package,
        part.tolerance,
        part.voltage,
        part.dielectric,
    )
    # 价格只回填给无单价的批次
    if product.moq_price is not None:
        for batch in part.batches:
            if batch.unit_price is None:
                batch.unit_price = product.moq_price
