"""BOM 文本解析器单元测试"""

from app.parsers.bom import infer_category_from_unit, parse_bom_text, split_tolerance


def test_parse_comma_csv_common_headers() -> None:
    text = (
        "Designator,Comment,Footprint,Quantity,Manufacturer Part\n"
        "R1,10k,0603,2,RC0603FR-0710KL\n"
        "C1,100nF,0805,5,CC0805KRX7R9BB104\n"
    )
    rows = parse_bom_text(text)
    assert len(rows) == 2
    r1 = rows[0]
    assert r1["value"] == "10k"
    assert r1["package"] == "0603"
    assert r1["quantity"] == "2"
    assert r1["mpn"] == "RC0603FR-0710KL"
    assert r1["designator"] == "R1"
    assert rows[1]["value"] == "100nF"


def test_parse_tab_separated_chinese_headers() -> None:
    text = "位号\t值\t封装\t数量\t厂商料号\nR1\t10k\t0603\t2\tRC0603\nR2\t100nF\t0805\t1\tCC0805\n"
    rows = parse_bom_text(text)
    assert len(rows) == 2
    assert rows[0]["value"] == "10k"
    assert rows[1]["value"] == "100nF"
    assert rows[1]["package"] == "0805"


def test_parse_empty_text() -> None:
    assert parse_bom_text("") == []
    assert parse_bom_text("   ") == []


def test_split_tolerance() -> None:
    assert split_tolerance("10k 1%") == ("10k", "1%")
    assert split_tolerance("10k") == ("10k", "")
    assert split_tolerance("100nF ±5%") == ("100nF", "±5%")
    assert split_tolerance("") == ("", "")


def test_infer_category_from_unit() -> None:
    assert infer_category_from_unit("F") == "电容"
    assert infer_category_from_unit("H") == "电感"
    assert infer_category_from_unit("Ω") == "电阻"
    assert infer_category_from_unit("") is None
    assert infer_category_from_unit("V") is None
