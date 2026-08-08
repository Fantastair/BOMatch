"""pytest 全局配置：测试前把数据库指向临时文件，避免污染真实数据"""

import os
import tempfile
from unittest.mock import patch

import pytest

_tmp_dir = tempfile.mkdtemp(prefix="bomatch-test-")
os.environ["BOMATCH_DB_PATH"] = os.path.join(_tmp_dir, "test.db")
os.environ["BOMATCH_SECRET_KEY"] = "test-secret-key"
os.environ["BOMATCH_INIT_PASSWORD"] = "testpass123"


@pytest.fixture(autouse=True)
def _clean_database():
    """每个测试前清空并重建数据库，保证测试相互隔离"""
    from app.auth import create_default_user_if_needed
    from app.db import Base, engine
    from app.seed import seed_categories

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    seed_categories()
    create_default_user_if_needed()
    yield


@pytest.fixture(autouse=True)
def _no_lcsc_network():
    """屏蔽新建料号保存时的真实立创同步（create_part 现为「先同步、后跳转」），
    避免测试联网/变慢；需要真实同步的测试可内部再 patch 覆盖。"""
    with patch("app.routers.parts.query_product_detailed", return_value=(None, "测试环境跳过")):
        yield
