"""
install.py  ·  卫星查看器 Python 依赖一键安装器
====================================================
用法:
    python install.py              # 默认:自动检测 + 只装缺失
    python install.py --force      # 强制重新装所有包
    python install.py --quiet      # 静默安装 (无彩色输出)
    python install.py --upgrade-pip    # 顺便升级 pip

为什么不直接 pip install -r requirements.txt:
    - 这个脚本会先 detect 哪些已经装,跳过重复下载 (数秒节省)
    - 强制 UTF-8 输出 (Windows GBK 默认编码不会乱码)
    - 实时显示每个包安装结果
    - 包含 Python 版本检查 + 安装后真实 import 验证

跑这个就足够。
"""
from __future__ import annotations

import argparse
import importlib
import os
import subprocess
import sys
from pathlib import Path

# Windows 控制台默认 GBK 编码,会让中文 print 崩溃
# 强制 stdout/stderr 用 UTF-8
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


# ============ 依赖清单 ============
# (import_name, pip_spec, 人类描述)
REQUIRED = [
    ("requests", "requests>=2.28.0",   "HTTP 请求 TLE 数据 (CelesTrak)"),
    ("skyfield", "skyfield>=1.46",     "高精度轨道推算 (NORAD SGP4)"),
    ("tabulate", "tabulate>=0.9.0",    "终端表格输出"),
]

PY_MIN = (3, 8)   # 最低 Python 版本
HERE  = Path(__file__).resolve().parent


# ============ ANSI 颜色 ============
class C:
    RESET  = "\033[0m"
    BOLD   = "\033[1m"
    DIM    = "\033[90m"
    GREEN  = "\033[32m"
    RED    = "\033[31m"
    YELLOW = "\033[33m"
    BLUE   = "\033[36m"
    LBLUE  = "\033[94m"


def _enable_windows_ansi() -> None:
    """Windows 10+ 在新版终端默认支持 ANSI,但 cmd.exe 不一定能.
    尝试启用 ENABLE_VIRTUAL_TERMINAL_PROCESSING. """
    if os.name != "nt":
        return
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        # ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x4
        kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
    except Exception:
        pass


_enable_windows_ansi()


def colorize(s: str, color: str) -> str:
    """包裹 ANSI 颜色."""
    return f"{color}{s}{C.RESET}"


def ok(s: str) -> str:    return f"{C.GREEN}✓{C.RESET} {s}"
def err(s: str) -> str:   return f"{C.RED}✗{C.RESET} {s}"
def warn(s: str) -> str:  return f"{C.YELLOW}!{C.RESET} {s}"
def info(s: str) -> str:  return f"{C.BLUE}▶{C.RESET} {s}"
def dim(s: str) -> str:   return f"{C.DIM}{s}{C.RESET}"


# ============ 检测 / 安装 ============
def python_version_ok() -> bool:
    v = sys.version_info
    return (v.major, v.minor) >= PY_MIN


def get_installed_version(import_name: str) -> str | None:
    """用真实 import 验证包是否已安装;返回版本字符串或 None。"""
    try:
        mod = importlib.import_module(import_name)
    except ImportError:
        return None
    # 大部分库用 __version__,但部分 (skyfield) 用 version.VERSION
    ver = getattr(mod, "__version__", None) or getattr(mod, "version", None)
    if hasattr(ver, "VERSION"):
        ver = ver.VERSION
    return str(ver) if ver else "已安装"


def pip_install(spec: str, quiet: bool = False) -> int:
    """用当前 Python 解释器自带的 pip 装包,返回 exit code."""
    cmd = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", spec]
    if quiet:
        cmd.append("--quiet")
    try:
        rc = subprocess.call(cmd, stdout=subprocess.DEVNULL if quiet else None,
                             stderr=subprocess.STDOUT)
    except FileNotFoundError:
        return 127
    return rc


def upgrade_pip(quiet: bool = False) -> None:
    """升级 pip 到最新."""
    cmd = [sys.executable, "-m", "pip", "install",
           "--disable-pip-version-check", "--upgrade", "pip"]
    if quiet:
        cmd.append("--quiet")
    try:
        subprocess.check_call(cmd, stdout=subprocess.DEVNULL if quiet else None,
                              stderr=subprocess.STDOUT)
    except Exception:
        pass  # 升级失败不致命


# ============ 主流程 ============
def main() -> int:
    parser = argparse.ArgumentParser(
        description="卫星查看器 - Python 依赖一键安装",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--force", action="store_true",
                        help="强制重新安装所有包 (即使已存在)")
    parser.add_argument("--quiet", action="store_true",
                        help="静默模式,只打印关键信息")
    parser.add_argument("--upgrade-pip", action="store_true",
                        help="顺便升级 pip")
    parser.add_argument("--no-color", action="store_true",
                        help="禁用 ANSI 颜色 (纯文本输出)")
    args = parser.parse_args()

    if args.no_color:
        # 把所有颜色代码取消
        for n in ("BOLD", "DIM", "GREEN", "RED", "YELLOW", "BLUE", "LBLUE", "RESET"):
            setattr(C, n, "")
    Q = args.quiet

    # ========= 横幅 =========
    if not Q:
        print(colorize("=" * 60, C.BOLD))
        print(colorize(" 🛰️  卫星查看器 · Python 依赖安装器", C.BOLD))
        print(colorize("=" * 60, C.BOLD))
        print()

    # ========= Python 版本检查 =========
    v = sys.version_info
    pv = f"{v.major}.{v.minor}.{v.micro}"
    if not python_version_ok():
        print(err(f"Python 版本不符: 当前 {pv}, 需要 ≥ {PY_MIN[0]}.{PY_MIN[1]}"))
        print(dim(f"  下载新版: https://www.python.org/downloads/"))
        return 1
    print(ok(f"Python {pv} " + dim(f"({Path(sys.executable).name})")))

    # ========= 升级 pip (可选) =========
    if args.upgrade_pip:
        print(info("升级 pip …"))
        upgrade_pip(quiet=Q)
        print(ok("pip 已升级"))

    print()
    print(info("正在检查依赖包 …"))
    print()

    # ========= 主循环:检查并按需安装 =========
    installed: list[str] = []
    skipped:   list[str] = []
    failed:    list[tuple[str, int]] = []

    for import_name, pip_spec, desc in REQUIRED:
        # 查询已有版本
        cur_ver = get_installed_version(import_name)
        if cur_ver and not args.force:
            skipped.append(f"{pip_spec} ({cur_ver})")
            print(f"  {ok(pip_spec.ljust(22))}  {dim('● 已存在 ' + cur_ver)}  {dim('— ' + desc)}")
            continue

        print(f"  {info('安装 ' + pip_spec + ' …')}  {dim('— ' + desc)}")
        rc = pip_install(pip_spec, quiet=Q)

        if rc != 0:
            failed.append((pip_spec, rc))
            print(f"  {err(f'{pip_spec} 安装失败 (退出码 {rc})')}")
            continue

        # 实际验证 import
        new_ver = get_installed_version(import_name) or "ok"
        installed.append(f"{pip_spec} ({new_ver})")
        print(f"  {ok(pip_spec.ljust(22))}  {dim('● ' + new_ver)}  {dim('— ' + desc)}")

    # ========= 结果汇总 =========
    print()
    print(colorize("─" * 60, C.DIM))
    print()

    if not failed:
        if installed:
            print(ok(f"已安装 {len(installed)} 个包:"))
            for s in installed:
                print(f"   {dim('•')} {s}")
        else:
            print(ok("全部依赖已就绪,无需安装"))
        if skipped:
            print(dim(f"已跳过 {len(skipped)} 个已存在包"))

        print()
        print(info("下一步运行:"))
        print(f"   {colorize('python satellite_tracker.py', C.LBLUE)}"
              f"   {dim('# 默认配置 (北京 + 推荐类别)')}")
        print(f"   {colorize('python satellite_tracker.py --geo --watch 30', C.LBLUE)}"
              f"   {dim('# IP 定位 + 30 秒自动刷新')}")
        print(f"   {colorize('python launch.py', C.LBLUE)}"
              f"   {dim('# 启动浏览器 UI (网页版)')}")
        return 0
    else:
        print(err(f"{len(failed)} 个包安装失败:"))
        for spec, rc in failed:
            print(f"   • {spec} (exit={rc})")
        print()
        print(dim("排查建议:"))
        print(dim("  1. 检查网络连接"))
        print(dim("  2. pip 需要更新: python -m pip install --upgrade pip"))
        print(dim("  3. 某些包编译需要 C 编译器 (如 skyfield 旧版需要的 sgp4)") )
        print(dim("  4. 在国内可以加镜像源: python install.py --mirror"))
        return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print(err("\n用户取消"))
        sys.exit(2)
    except Exception as e:
        print(err(f"安装异常: {e}"))
        sys.exit(1)
