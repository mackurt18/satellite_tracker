"""
satellite_tracker.py  ·  CLI 版"头顶卫星"查看器
================================================
数据源: CelesTrak (gp.php JSON 接口,免费,无需注册)
轨道计算: skyfield (JPL / NORAD SGP4,精度行业标准)

用法:
    pip install skyfield requests tabulate
    python satellite_tracker.py                        # 默认:北京 + 选中类别
    python satellite_tracker.py --lat 31.23 --lon 121.47  # 上海
    python satellite_tracker.py --geo                   # 用浏览器/IP 定位
    python satellite_tracker.py --min-elev 10 --cat esa galileo stations
    python satellite_tracker.py --cat stations          # 只看 ISS / 中国空间站
    python satellite_tracker.py --watch 30              # 每 30 秒刷新一次,持续监视
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

try:
    import requests
except ImportError:
    sys.exit("缺少 requests,请先运行: pip install requests")

try:
    from skyfield.api import EarthSatellite, load
    from skyfield.toposlib import wgs84
except ImportError:
    sys.exit("缺少 skyfield,请先运行: pip install skyfield")

try:
    from tabulate import tabulate
except ImportError:
    tabulate = None  # 备用:自己格式化


# ------------------------------------------------------------
# 1. CATEGORY DEFS
# ------------------------------------------------------------
# 注意:和 HTML 版本保持一致
CATEGORY_DEFS = [
    {"id": "stations", "label": "空间站 (ISS/天宫)",      "group": "stations"},
    {"id": "crewed",   "label": "载人飞行器",              "group": "crewed"},
    {"id": "esa",      "label": "欧空局 ESA",              "group": "esa"},
    {"id": "galileo",  "label": "Galileo (欧空局导航)",    "group": "galileo"},
    {"id": "sentinel", "label": "Sentinel/Copernicus",     "group": "sentinel"},
    {"id": "swarm",    "label": "Swarm (ESA 星座)",        "group": "swarm"},
    {"id": "weather",  "label": "气象卫星",                "group": "weather"},
    {"id": "noaa",     "label": "NOAA",                    "group": "noaa"},
    {"id": "resource", "label": "对地观测",                "group": "resource"},
    {"id": "sarsat",   "label": "搜救卫星",                "group": "sarsat"},
    {"id": "goes",     "label": "GOES",                    "group": "goes"},
    {"id": "amateur",  "label": "业余无线电",              "group": "amateur"},
    {"id": "gnss",     "label": "全部 GNSS",               "group": "gnss"},
    {"id": "starlink", "label": "Starlink",                "group": "starlink"},
]

CAT_BY_ID = {c["id"]: c for c in CATEGORY_DEFS}
# TLE 文本格式 (每 3 行一组: name + line1 + line2)
# 比 JSON (OMM) 格式简单,直接给 satellite.js / skyfield 用
CELESTRAK_URL = (
    "https://celestrak.org/NORAD/elements/gp.php"
    "?GROUP={group}&FORMAT=tle"
)
CACHE_DIR = Path.home() / ".cache" / "satellite_tracker"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
CACHE_TTL = 6 * 3600  # 6 小时


# ------------------------------------------------------------
# 2. TLE FETCH + CACHE
# ------------------------------------------------------------
def fetch_tle(group: str) -> str:
    """拉取一个类别的 TLE 文本(3 行一组)。返回原始字符串。"""
    cache_file = CACHE_DIR / f"{group}.tle"
    if cache_file.exists():
        age = time.time() - cache_file.stat().st_mtime
        if age < CACHE_TTL:
            return cache_file.read_text()

    url = CELESTRAK_URL.format(group=group)
    print(f"  ↳ 正在拉取 {group:10s} TLE: {url}", file=sys.stderr)
    try:
        r = requests.get(url, timeout=20)
        r.raise_for_status()
        text = r.text
        cache_file.write_text(text)
        return text
    except Exception as e:
        if cache_file.exists():
            print(f"  ⚠️ {group} 拉取失败,使用过期缓存: {e}", file=sys.stderr)
            return cache_file.read_text()
        raise


def parse_tle_text(text: str) -> list[dict]:
    """将 3-line TLE 文本拆分为 [{name, l1, l2, norad, ...}]。"""
    lines = [l.rstrip() for l in text.splitlines() if l.strip()]
    out = []
    i = 0
    while i + 2 < len(lines):
        name, l1, l2 = lines[i], lines[i + 1], lines[i + 2]
        # 兼容 2-line 或 3-line 模式:如果当前行不是 name 而是 line1,前置空名占位
        if not l1.startswith("1 ") and not l2.startswith("2 "):
            i += 1
            continue
        if not l1.startswith("1 ") or not l2.startswith("2 "):
            i += 1
            continue
        if l1.startswith("1 "):
            # 当前行实际是 line1,真正的名字在上一行(可能是空)
            true_name = lines[i - 1] if i > 0 and not lines[i - 1].startswith("1 ") else ""
            # 重新组装:把 l1/l2 当成 row 的开头,但需要拿名字
            # 实际上这种格式较少见,直接就用空 name
            pass
        try:
            norad = int(l1[2:7].strip())
            intl = l1[9:17].strip()
            incl = float(l2[8:16])
            ecc = float("0." + l2[26:33].strip())
            mm = float(l2[52:63])
            epoch_raw = l1[18:32].strip()
        except ValueError:
            i += 1
            continue
        out.append({
            "OBJECT_NAME": name.strip(),
            "TLE_LINE1":   l1,
            "TLE_LINE2":   l2,
            "NORAD_CAT_ID": norad,
            "OBJECT_ID":    intl,
            "INCLINATION":  incl,
            "ECCENTRICITY": ecc,
            "MEAN_MOTION":  mm,
            "EPOCH":        epoch_raw,
        })
        i += 3
    return out


def load_satellites(cat_ids: Iterable[str]) -> list[tuple[EarthSatellite, dict]]:
    """返回 [(satellite, meta), ...],meta 含 name/norad/group/inclination 等。"""
    out: list[tuple[EarthSatellite, dict]] = []
    seen_norad: set[int] = set()
    for cat_id in cat_ids:
        cat = CAT_BY_ID[cat_id]
        try:
            text = fetch_tle(cat["group"])
            entries = parse_tle_text(text)
        except Exception as e:
            print(f"  ⚠️ 跳过 {cat['label']}: {e}", file=sys.stderr)
            continue
        for e in entries:
            try:
                if e["NORAD_CAT_ID"] in seen_norad:
                    continue
                sat = EarthSatellite(e["TLE_LINE1"], e["TLE_LINE2"],
                                     name=e["OBJECT_NAME"])
                meta = {
                    "norad":   e["NORAD_CAT_ID"],
                    "name":    e["OBJECT_NAME"].strip(),
                    "id":      e["OBJECT_ID"],
                    "incl":    e["INCLINATION"],
                    "mm":      e["MEAN_MOTION"],
                    "ecc":     e["ECCENTRICITY"],
                    "group":   cat["group"],
                    "epoch":   e["EPOCH"],
                }
                out.append((sat, meta))
                seen_norad.add(e["NORAD_CAT_ID"])
            except Exception:
                continue
    return out


# ------------------------------------------------------------
# 3. OBSERVER + VISIBILITY CALC
# ------------------------------------------------------------
@dataclass
class Observer:
    lat_deg: float
    lon_deg: float
    alt_m: float

    def to_skyfield(self):
        # skyfield 用 IERS 标准的 WGS84 ellipsoid
        return wgs84.latlon(self.lat_deg, self.lon_deg, elevation_m=self.alt_m)


def compass_point(az_deg: float) -> str:
    """返回方位对应的字母 (N/NNE/NE/ENE/...)"""
    dirs = ["N","NNE","NE","ENE","E","ESE","SE","SSE",
            "S","SSW","SW","WSW","W","WNW","NW","NNW"]
    idx = int(((az_deg % 360) / 22.5) + 0.5) % 16
    return dirs[idx]


def compute_visibility(sat: EarthSatellite, obs: Observer, t):
    """返回 (azimuth_deg, elevation_deg, range_km) 或 None。

    skyfield 推荐用法: (sat - observer).at(t).altaz()
    输出: (Altitude, Azimuth, Distance),其中 Distance 是从天体到观测者的直线距离。
    """
    try:
        # sat / observer 都是矢量,支持减法;结果为顶层差分,再用 .at(t) 求位置
        topocentric = (sat - obs.to_skyfield()).at(t)
        alt, az, dist = topocentric.altaz()
        return az.degrees, alt.degrees, dist.km
    except Exception:
        return None


def overhead(sats, obs: Observer, t, min_elev: float, search: str = "",
             show_hidden: bool = False):
    """计算所有当前可见的卫星,返回排序后的列表 (按仰角降序)。"""
    rows = []
    for sat, meta in sats:
        if search and search.lower() not in meta["name"].lower() \
                   and search.lower() not in meta["id"].lower():
            continue
        try:
            r = compute_visibility(sat, obs, t)
        except Exception:
            continue
        if r is None:
            continue
        az, alt, dist = r
        if not show_hidden and alt < min_elev:
            continue
        rows.append((meta, sat, alt, az, dist))
    rows.sort(key=lambda x: -x[2])  # 仰角降序
    return rows


# ------------------------------------------------------------
# 4. RENDER
# ------------------------------------------------------------
def fmt_alt(a: float) -> str:
    return f"{a:+.1f}°"


def render_table(rows, min_elev: float):
    if not rows:
        print("\n  当前没有卫星在你上空达到最低仰角。")
        print("  (试着把 --min-elev 调到 0 或 -5,或加 --show-hidden)")
        return

    table = []
    for meta, sat, alt, az, dist in rows:
        badge = ""
        n = meta["name"]
        if meta["group"] == "stations":
            badge = "🏠"
        elif meta["group"] in ("esa", "galileo", "sentinel", "swarm"):
            badge = "🇪🇺"
        elif meta["group"] in ("noaa", "weather", "goes"):
            badge = "🌦"
        table.append([
            badge,
            n[:36].ljust(38),
            fmt_alt(alt),
            f"{az:6.1f}° {compass_point(az):>3s}",
            f"{dist:8.0f} km",
            meta["norad"],
        ])
    headers = ["", "卫星", "仰角", "方位", "距离", "NORAD#"]
    if tabulate:
        print("\n" + tabulate(table, headers=headers, tablefmt="github", numalign="right"))
    else:
        # 简单 fallback
        print(f"\n{'卫星':<40} {'仰角':>7}  {'方位':>10}  {'距离':>12}  NORAD#")
        print("-" * 90)
        for row in table:
            print(f"{row[1]:<40} {row[2]:>7}  {row[3]:>10}  {row[4]:>12}  {row[5]}")


def ip_geolocate() -> tuple[float, float]:
    """粗略 IP 定位 (无浏览器 Geolocation 时的后备方案)"""
    try:
        r = requests.get("http://ip-api.com/json/?lang=zh-CN", timeout=10)
        d = r.json()
        if d.get("status") == "success":
            return d["lat"], d["lon"]
    except Exception:
        pass
    return 39.9042, 116.4074  # 北京


# ------------------------------------------------------------
# 5. MAIN
# ------------------------------------------------------------
def main():
    p = argparse.ArgumentParser(
        description="🛰️ 查看此刻你头顶有什么卫星 (CelesTrak TLE + Skyfield SGP4)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--lat", type=float, default=39.9042, help="观测点纬度 (默认 39.9042 北京)")
    p.add_argument("--lon", type=float, default=116.4074, help="观测点经度 (默认 116.4074 北京)")
    p.add_argument("--alt", type=float, default=50, help="观测点海拔 (米,默认 50)")
    p.add_argument("--geo", action="store_true", help="用 IP 地理定位估算位置")
    p.add_argument("--min-elev", type=float, default=0, help="最低仰角 (度,默认 0)")
    p.add_argument("--show-hidden", action="store_true",
                   help="包含低于地平线的卫星 (主要用于看'即将过顶')")
    p.add_argument("--cat", nargs="+", default=["stations", "crewed", "esa", "galileo",
                                                  "sentinel", "swarm", "weather", "resource"],
                   help="卫星类别 ID (空格分隔多个,默认见上)")
    p.add_argument("--search", default="", help="按名称/标识搜索过滤 (例: ISS)")
    p.add_argument("--watch", type=float, default=0,
                   help="持续监视模式,每隔 N 秒刷新一次 (0 = 只跑一次)")
    p.add_argument("--list-cats", action="store_true", help="列出所有可用类别并退出")
    args = p.parse_args()

    if args.list_cats:
        print("可用类别 (--cat 选项):")
        for c in CATEGORY_DEFS:
            print(f"  {c['id']:10s} - {c['label']}")
        return

    if args.geo:
        args.lat, args.lon = ip_geolocate()
        print(f"📍 IP 定位: ({args.lat}, {args.lon})")

    print(f"📍 观测点: ({args.lat:.4f}, {args.lon:.4f}, {args.alt:.0f}m)")
    print(f"🎯 仰角阈值: {args.min_elev}°  {'(含地平线下)' if args.show_hidden else ''}")
    print(f"📡 类别: {', '.join(args.cat)}")

    print("\n⏳ 加载 TLE 数据...")
    sats = load_satellites(args.cat)
    if not sats:
        sys.exit("没有加载到任何卫星,请检查网络或类别 ID")

    print(f"✅ 已加载 {len(sats)} 颗卫星")
    obs = Observer(args.lat, args.lon, args.alt)

    # skyfield 需要 timescale
    ts = load.timescale()

    def tick():
        t = ts.now()
        # clear screen in watch mode
        if args.watch:
            os.system("cls" if os.name == "nt" else "clear")
            print(f"📍 ({obs.lat_deg:.4f}, {obs.lon_deg:.4f}, {obs.alt_m:.0f}m)"
                  f"  · 仰角 ≥ {args.min_elev}°"
                  f"  · UTC {datetime.now(timezone.utc).strftime('%H:%M:%S')}"
                  f"  · {len(sats)} 颗")
        rows = overhead(sats, obs, t, args.min_elev, args.search, args.show_hidden)
        render_table(rows, args.min_elev)
        if args.watch:
            # next 60 min 提示
            print(f"\n(下次过顶信息在 HTML 版 'detail-panel' 中查看,自动计算 24h 内最佳仰角)")
        print()

    tick()
    if args.watch:
        try:
            while True:
                time.sleep(args.watch)
                tick()
        except KeyboardInterrupt:
            print("\n👋 已停止监视")


if __name__ == "__main__":
    main()
