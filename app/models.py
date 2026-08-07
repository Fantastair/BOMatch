"""数据库模型"""

import re
from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

_LCSC_CODE_RE = re.compile(r"^C\d+$")


class User(Base):
    """登录用户（单用户系统，通常仅一个 admin）"""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class Category(Base):
    """元件类别（电阻/电容/IC/...）"""

    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(String(255))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    parts: Mapped[list["Part"]] = relationship(back_populates="category")


class Location(Base):
    """库位（抽屉/格/盒，M2 起被批次引用）"""

    __tablename__ = "locations"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(String(255))


class Part(Base):
    """元件料号（含解析后的参数与等效键）"""

    __tablename__ = "parts"

    id: Mapped[int] = mapped_column(primary_key=True)
    mpn: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    manufacturer: Mapped[str | None] = mapped_column(String(128))
    lcsc_code: Mapped[str | None] = mapped_column(String(32), index=True)  # 立创商城编号（C 开头）

    @property
    def lcsc_code_effective(self) -> str | None:
        """实际立创编号：优先 lcsc_code 字段；否则 mpn 为立创编号格式（C+数字）时用它"""
        if self.lcsc_code:
            return self.lcsc_code
        if _LCSC_CODE_RE.match(self.mpn or ""):
            return self.mpn
        return None

    category_id: Mapped[int] = mapped_column(
        ForeignKey("categories.id"), nullable=False, index=True
    )
    category: Mapped["Category"] = relationship(back_populates="parts")

    # 解析后的参数（value 为 base 单位数值）
    value: Mapped[float | None] = mapped_column(Float)
    value_unit: Mapped[str] = mapped_column(String(16), default="")
    value_raw: Mapped[str | None] = mapped_column(String(64))  # 原始数值文本（回填/展示用）
    package: Mapped[str | None] = mapped_column(String(64), index=True)
    tolerance: Mapped[str | None] = mapped_column(String(16))
    voltage: Mapped[float | None] = mapped_column(Float)
    dielectric: Mapped[str | None] = mapped_column(String(16))

    # 等效键（等效组聚合依据）
    canonical_key: Mapped[str] = mapped_column(String(255), nullable=False, index=True)

    description: Mapped[str | None] = mapped_column(Text)
    datasheet_url: Mapped[str | None] = mapped_column(String(512))

    batches: Mapped[list["Batch"]] = relationship(
        back_populates="part", cascade="all, delete-orphan"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class Batch(Base):
    """库存批次（一次入库的一批元件，M2 起使用）"""

    __tablename__ = "batches"

    id: Mapped[int] = mapped_column(primary_key=True)
    part_id: Mapped[int] = mapped_column(ForeignKey("parts.id"), nullable=False, index=True)
    part: Mapped["Part"] = relationship(back_populates="batches")

    location_id: Mapped[int | None] = mapped_column(ForeignKey("locations.id"), index=True)
    location: Mapped["Location | None"] = relationship()

    quantity: Mapped[int] = mapped_column(Integer, default=0)  # 当前剩余数量
    unit_price: Mapped[float | None] = mapped_column(Float)  # 可选单价（金额统计用）
    source: Mapped[str | None] = mapped_column(String(128))  # 来源（采购单/旧料）
    note: Mapped[str | None] = mapped_column(String(255))

    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class Project(Base):
    """设计项目（BOM 的载体）"""

    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(String(255))
    bom_items: Mapped[list["BOMItem"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class BOMItem(Base):
    """BOM 条目（项目的一行，保留原始信息并记录匹配结果）"""

    __tablename__ = "bom_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    project: Mapped["Project"] = relationship(back_populates="bom_items")

    # 匹配结果
    part_id: Mapped[int | None] = mapped_column(ForeignKey("parts.id"), index=True)
    part: Mapped["Part | None"] = relationship()
    canonical_key: Mapped[str] = mapped_column(String(255), default="", index=True)

    quantity: Mapped[int] = mapped_column(Integer, default=1)

    # 原始行信息
    designator: Mapped[str | None] = mapped_column(String(255))  # 位号（可能多个）
    value_raw: Mapped[str | None] = mapped_column(String(64))
    package: Mapped[str | None] = mapped_column(String(64))
    mpn_raw: Mapped[str | None] = mapped_column(String(128))
    manufacturer_raw: Mapped[str | None] = mapped_column(String(128))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
