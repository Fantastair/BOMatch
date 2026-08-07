"""
本脚本旨在集成常用的的项目开发指令。
"""

import subprocess
import sys
from functools import wraps
from pathlib import Path
from time import perf_counter_ns as get_time_ns

import rich
import rich.console
import rich.style
import typer

CWD = Path(__file__).parent
CONSOLE = rich.console.Console()

NORMAL_STYLE = rich.style.Style(color="white")
ERROR_STYLE = rich.style.Style(color="red")
SUCCESSFUL_STYLE = rich.style.Style(color="green")
WARNING_STYLE = rich.style.Style(color="yellow")
INFO_STYLE = rich.style.Style(color="blue")
DEBUG_STYLE = rich.style.Style(color="cyan")
TITLE_STYLE = rich.style.Style(color="deep_pink4", bold=True)
COMMENT_STYLE = rich.style.Style(color="grey50")


def prints(*msg_list: tuple[str, rich.style.Style]) -> None:
    """使用 rich 打印多条带有样式的消息"""
    for msg, style in msg_list:
        CONSOLE.print(msg, style=style, end="")
    print()


def auto_timeunit(time_ns: int) -> str:
    """自动转换时间单位，返回带有单位的字符串"""
    elapsed_time: float = float(time_ns)

    if elapsed_time < 1000:
        return f"{elapsed_time:.2f} ns"
    elapsed_time /= 1000
    if elapsed_time < 1000:
        return f"{elapsed_time:.2f} μs"
    elapsed_time /= 1000
    if elapsed_time < 1000:
        return f"{elapsed_time:.2f} ms"
    elapsed_time /= 1000
    if elapsed_time < 60:
        return f"{elapsed_time:.2f} s"
    elapsed_time /= 60
    if elapsed_time < 60:
        return f"{elapsed_time:.2f} min"
    elapsed_time /= 60
    return f"{elapsed_time:.2f} h"


def cmd_run(
    cmd: list[str],
    capture_output: bool = False,
    error_on_output: bool = False,
    cwd: Path = CWD,
) -> str:
    """模拟命令行终端运行命令"""
    if error_on_output:
        capture_output = True

    norm_cmd = [str(i) for i in cmd]
    prints(
        (r"\[run] ", TITLE_STYLE),
        (f"[cyan]{' '.join(norm_cmd)}[/]", DEBUG_STYLE),
    )

    result = subprocess.run(
        norm_cmd,
        stdout=subprocess.PIPE if capture_output else sys.stdout,
        stderr=subprocess.STDOUT,
        text=capture_output,
        cwd=cwd,
        check=True,
    )

    if result.stdout:
        print(result.stdout, end="", flush=True)

    if (error_on_output and result.stdout) and not result.returncode:
        result.returncode = 1

    result.check_returncode()
    return result.stdout.strip() if capture_output else ""


app = typer.Typer(
    help="开发相关的命令集合",
    add_completion=False,
    no_args_is_help=True,
)


def app_command(
    typer_app: typer.Typer = app,
    name: str | None = None,
    rich_help_panel: str | None = None,
):
    """装饰器，用于包装命令函数，添加统一的日志输出和错误处理"""

    def command(func):
        @typer_app.command(name=name, rich_help_panel=rich_help_panel)
        @wraps(func)
        def command_func(*args, **kwargs):
            func_name = name if name is not None else func.__name__
            start_time = get_time_ns()
            prints(
                (r"\[dev.py] ", TITLE_STYLE),
                ("运行命令 ", NORMAL_STYLE),
                (f"{func_name}", INFO_STYLE),
            )

            try:
                result = func(*args, **kwargs)
            except subprocess.CalledProcessError:
                prints(
                    (r"\[dev.py] ", TITLE_STYLE),
                    (f'命令 "{func_name}" 运行失败，请检查错误信息', ERROR_STYLE),
                )
                sys.exit(1)
            except KeyboardInterrupt:
                prints(
                    (r"\[dev.py] ", TITLE_STYLE),
                    (f'命令 "{func_name}" 被用户中断', WARNING_STYLE),
                )
                sys.exit(1)
            except Exception as e:
                prints(
                    (r"\[dev.py] ", TITLE_STYLE),
                    (f'命令 "{func_name}" 运行失败，发生错误: {e}', ERROR_STYLE),
                )
                sys.exit(1)

            end_time = get_time_ns()
            prints(
                (r"\[dev.py]", TITLE_STYLE),
                (
                    f" 命令 {func_name} 执行成功,",
                    SUCCESSFUL_STYLE,
                ),
                (
                    f" 耗时：[grey50]{auto_timeunit(end_time - start_time)}[/]",
                    COMMENT_STYLE,
                ),
            )
            return result

        return command_func

    return command


@app_command(app)
def check():
    """代码审查"""
    prints(
        (r"\[ruff] ", TITLE_STYLE),
        ("格式化代码", NORMAL_STYLE),
    )
    try:
        cmd_run(["uv", "run", "ruff", "format"])
    except subprocess.CalledProcessError:
        prints(
            (r"\[ruff] ", TITLE_STYLE),
            ("代码格式化失败，请检查错误信息", ERROR_STYLE),
        )
        raise

    prints(
        (r"\[ruff] ", TITLE_STYLE),
        ("分析代码质量", NORMAL_STYLE),
    )
    try:
        cmd_run(["uv", "run", "ruff", "check", "--fix"])
    except subprocess.CalledProcessError:
        prints(
            (r"\[ruff] ", TITLE_STYLE),
            ("代码质量分析失败，请检查错误信息", ERROR_STYLE),
        )
        raise

    prints(
        (r"\[ty] ", TITLE_STYLE),
        ("静态类型检查", NORMAL_STYLE),
    )
    try:
        cmd_run(["uv", "run", "ty", "check"])
    except subprocess.CalledProcessError:
        prints(
            (r"\[ty] ", TITLE_STYLE),
            ("静态类型检查失败，请检查错误信息", ERROR_STYLE),
        )
        raise


@app_command(app, name="test", rich_help_panel="项目命令")
def run_tests():
    """运行测试"""
    prints(
        (r"\[pytest] ", TITLE_STYLE),
        ("运行测试", NORMAL_STYLE),
    )
    try:
        cmd_run(["uv", "run", "pytest"])
    except subprocess.CalledProcessError:
        prints(
            (r"\[pytest] ", TITLE_STYLE),
            ("测试运行失败，请检查错误信息", ERROR_STYLE),
        )
        raise


@app_command(app, name="run", rich_help_panel="项目命令")
def run_dev_server():
    """启动开发服务器（uvicorn --reload，Ctrl+C 停止）"""
    prints(
        (r"\[uvicorn] ", TITLE_STYLE),
        ("启动开发服务器", NORMAL_STYLE),
    )
    cmd_run(["uv", "run", "uvicorn", "app.main:app", "--reload", "--port", "8000"])


@app_command(app, name="db-init", rich_help_panel="项目命令")
def init_database():
    """初始化 SQLite 数据库（建表，幂等）"""
    prints(
        (r"\[db] ", TITLE_STYLE),
        ("初始化数据库", NORMAL_STYLE),
    )
    try:
        cmd_run(["uv", "run", "python", "-c", "from app.db import init_db; init_db()"])
    except subprocess.CalledProcessError:
        prints(
            (r"\[db] ", TITLE_STYLE),
            ("数据库初始化失败，请检查错误信息", ERROR_STYLE),
        )
        raise


if __name__ == "__main__":
    app()
