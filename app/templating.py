"""模板与静态资源配置（独立模块，避免 main 与 routers 循环导入）"""

from pathlib import Path

from fastapi.templating import Jinja2Templates

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES = Jinja2Templates(directory=BASE_DIR / "templates")
STATIC_DIR = BASE_DIR / "static"
