"""服务层：库存查询（供匹配等场景复用）"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Batch, Part


def _canonical_conditions(canonical_key: str) -> list:
    """生成 canonical_key 的匹配条件（含宽松回退）。

    - key 未指定容差/耐压/介质（末尾段为空）：前缀通配，匹配任意容差等的库存
    - key 完整：精确匹配（含去掉末段的宽松候选）
    """
    parts = canonical_key.split("|")
    if parts and parts[0] in ("R", "C") and len(parts) >= 3 and parts[-1] == "":
        prefix = "|".join(parts[:3]) + "|"
        return [Part.canonical_key.like(prefix + "%")]
    return [Part.canonical_key.in_(_match_candidates(canonical_key))]


def stock_for_canonical_key(session: Session, canonical_key: str) -> int:
    """某等效组（canonical key）的当前总库存数量（含宽松回退）"""
    part_ids = select(Part.id).where(*_canonical_conditions(canonical_key))
    return (
        session.scalar(
            select(func.coalesce(func.sum(Batch.quantity), 0)).where(Batch.part_id.in_(part_ids))
        )
        or 0
    )


def find_part_for_canonical_key(session: Session, canonical_key: str) -> Part | None:
    """按等效键（含宽松回退）查找代表料号。"""
    return (
        session.execute(select(Part).where(*_canonical_conditions(canonical_key)).order_by(Part.id))
        .scalars()
        .first()
    )


def _match_candidates(canonical_key: str) -> list[str]:
    """完整 key 的候选列表（含去掉末段的宽松候选）。

    电阻 R|值|封装|容差 → 含 R|值|封装|（忽略容差）
    电容 C|值|封装|耐压|介质 → 含 C|值|封装||（忽略耐压介质）
    """
    parts = canonical_key.split("|")
    keys = [canonical_key]
    if parts and parts[0] == "R" and len(parts) >= 4:
        keys.append("|".join(parts[:3] + [""]))
    elif parts and parts[0] == "C" and len(parts) >= 5:
        keys.append("|".join(parts[:3] + ["", ""]))
    return keys
