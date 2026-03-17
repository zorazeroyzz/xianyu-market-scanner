"""
数据分析模块：从采集数据中提取市场洞察
"""
import json
import argparse
import logging
from pathlib import Path
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from typing import Optional

from utils import DataStore, setup_logging

logger = logging.getLogger("xianyu-scanner")


@dataclass
class GroupAnalysis:
    """单个赛道/关键词组的分析结果"""
    group_id: str
    label: str
    track: str

    # 基础统计
    total_items: int = 0
    total_keywords_scanned: int = 0

    # 价格分析
    price_min: float = 0
    price_max: float = 0
    price_mean: float = 0
    price_median: float = 0
    price_p25: float = 0  # 25 分位
    price_p75: float = 0  # 75 分位

    # 需求信号
    avg_want_count: float = 0
    max_want_count: int = 0
    avg_sold_count: float = 0
    total_sold_estimate: int = 0

    # 竞争分析
    unique_sellers: int = 0
    top_sellers: list = field(default_factory=list)  # [{seller_name, item_count, avg_price}]
    listings_density: float = 0  # 每个关键词平均商品数

    # 热门商品
    top_items_by_want: list = field(default_factory=list)
    top_items_by_sold: list = field(default_factory=list)

    # 综合评分 (0-100)
    demand_score: float = 0
    competition_score: float = 0
    profit_score: float = 0
    viability_score: float = 0

    # 关键词维度明细
    keyword_breakdown: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def analyze_group(group_id: str, items: list, label: str = "", track: str = "") -> GroupAnalysis:
    """分析单个组的所有商品数据"""

    analysis = GroupAnalysis(
        group_id=group_id,
        label=label,
        track=track,
        total_items=len(items),
    )

    if not items:
        return analysis

    # ── 价格分析 ──
    prices = sorted([it["price"] for it in items if it.get("price", 0) > 0])
    if prices:
        analysis.price_min = prices[0]
        analysis.price_max = prices[-1]
        analysis.price_mean = round(sum(prices) / len(prices), 2)
        analysis.price_median = prices[len(prices) // 2]
        analysis.price_p25 = prices[len(prices) // 4]
        analysis.price_p75 = prices[3 * len(prices) // 4]

    # ── 需求信号 ──
    want_counts = [it.get("want_count", 0) for it in items]
    sold_counts = [it.get("sold_count", 0) for it in items]

    analysis.avg_want_count = round(sum(want_counts) / max(len(want_counts), 1), 1)
    analysis.max_want_count = max(want_counts) if want_counts else 0
    analysis.avg_sold_count = round(sum(sold_counts) / max(len(sold_counts), 1), 1)
    analysis.total_sold_estimate = sum(sold_counts)

    # ── 竞争分析 ──
    seller_map = defaultdict(list)
    for it in items:
        sid = it.get("seller_id") or it.get("seller_name", "unknown")
        seller_map[sid].append(it)

    analysis.unique_sellers = len(seller_map)

    # Top 卖家
    seller_stats = []
    for sid, seller_items in seller_map.items():
        s_prices = [x["price"] for x in seller_items if x.get("price", 0) > 0]
        seller_stats.append({
            "seller_name": seller_items[0].get("seller_name", sid),
            "item_count": len(seller_items),
            "avg_price": round(sum(s_prices) / max(len(s_prices), 1), 2),
            "total_sold": sum(x.get("sold_count", 0) for x in seller_items),
        })
    seller_stats.sort(key=lambda x: x["total_sold"], reverse=True)
    analysis.top_sellers = seller_stats[:10]

    # 关键词维度
    kw_map = defaultdict(list)
    for it in items:
        kw = it.get("_keyword", "unknown")
        kw_map[kw].append(it)

    analysis.total_keywords_scanned = len(kw_map)
    analysis.listings_density = round(len(items) / max(len(kw_map), 1), 1)

    kw_breakdown = []
    for kw, kw_items in kw_map.items():
        kw_prices = [x["price"] for x in kw_items if x.get("price", 0) > 0]
        kw_breakdown.append({
            "keyword": kw,
            "count": len(kw_items),
            "avg_price": round(sum(kw_prices) / max(len(kw_prices), 1), 2),
            "max_want": max((x.get("want_count", 0) for x in kw_items), default=0),
        })
    kw_breakdown.sort(key=lambda x: x["count"], reverse=True)
    analysis.keyword_breakdown = kw_breakdown

    # ── 热门商品 ──
    items_by_want = sorted(items, key=lambda x: x.get("want_count", 0), reverse=True)
    analysis.top_items_by_want = [
        {"title": it["title"][:50], "price": it["price"], "want_count": it.get("want_count", 0)}
        for it in items_by_want[:5]
    ]

    items_by_sold = sorted(items, key=lambda x: x.get("sold_count", 0), reverse=True)
    analysis.top_items_by_sold = [
        {"title": it["title"][:50], "price": it["price"], "sold_count": it.get("sold_count", 0)}
        for it in items_by_sold[:5]
    ]

    # ── 综合评分 ──
    analysis.demand_score = _score_demand(analysis)
    analysis.competition_score = _score_competition(analysis)
    analysis.profit_score = _score_profit(analysis)
    analysis.viability_score = round(
        analysis.demand_score * 0.35
        + analysis.profit_score * 0.35
        + (100 - analysis.competition_score) * 0.30,
        1,
    )

    return analysis


def _score_demand(a: GroupAnalysis) -> float:
    """需求评分 (0-100)"""
    score = 0
    # 平均"想要"数
    if a.avg_want_count > 50:
        score += 40
    elif a.avg_want_count > 20:
        score += 30
    elif a.avg_want_count > 5:
        score += 20
    elif a.avg_want_count > 0:
        score += 10
    # 总销量
    if a.total_sold_estimate > 500:
        score += 40
    elif a.total_sold_estimate > 100:
        score += 30
    elif a.total_sold_estimate > 20:
        score += 20
    elif a.total_sold_estimate > 0:
        score += 10
    # 商品密度（越多说明需求越旺盛）
    if a.listings_density > 80:
        score += 20
    elif a.listings_density > 40:
        score += 15
    elif a.listings_density > 10:
        score += 10
    return min(score, 100)


def _score_competition(a: GroupAnalysis) -> float:
    """竞争强度评分 (0-100, 越高越卷)"""
    score = 0
    # 卖家数量
    if a.unique_sellers > 200:
        score += 50
    elif a.unique_sellers > 50:
        score += 35
    elif a.unique_sellers > 20:
        score += 20
    elif a.unique_sellers > 5:
        score += 10
    # 头部集中度
    if a.top_sellers:
        top3_share = sum(s["item_count"] for s in a.top_sellers[:3]) / max(a.total_items, 1)
        if top3_share > 0.5:
            score += 30  # 头部垄断
        elif top3_share > 0.3:
            score += 20
        else:
            score += 10
    # 价格战信号（价格方差小 = 卷）
    if a.price_p75 > 0 and a.price_p25 > 0:
        price_spread = (a.price_p75 - a.price_p25) / a.price_median if a.price_median > 0 else 0
        if price_spread < 0.3:
            score += 20  # 价格高度趋同，红海
        elif price_spread < 0.6:
            score += 10
    return min(score, 100)


def _score_profit(a: GroupAnalysis) -> float:
    """利润潜力评分 (0-100)"""
    score = 0
    # 中位价格（虚拟商品成本趋近零，价格即利润）
    if a.price_median > 100:
        score += 40
    elif a.price_median > 30:
        score += 30
    elif a.price_median > 10:
        score += 20
    elif a.price_median > 0:
        score += 10
    # 高价商品存在空间
    if a.price_p75 > 50:
        score += 20
    elif a.price_p75 > 20:
        score += 15
    # 可批量化（sold_count 高意味着可以规模化）
    if a.avg_sold_count > 10:
        score += 25
    elif a.avg_sold_count > 3:
        score += 15
    elif a.avg_sold_count > 0:
        score += 10
    # 价格分层空间（有高有低，可差异化）
    if a.price_max > a.price_median * 3:
        score += 15
    return min(score, 100)


def run_analysis(data_dir: str, config_path: Optional[str] = None) -> dict:
    """
    执行完整分析流程

    Returns:
        {
            "summary": {...},
            "groups": {group_id: GroupAnalysis, ...},
            "rankings": {...}
        }
    """
    store = DataStore(data_dir)
    records = store.load_all()

    if not records:
        logger.warning(f"数据目录 {data_dir} 中没有数据文件")
        logger.info("请先运行 scanner.py 采集数据")
        return {"summary": {}, "groups": {}, "rankings": {}}

    # 加载配置获取 label/track 信息
    group_meta = {}
    if config_path:
        config = json.loads(Path(config_path).read_text(encoding="utf-8"))
        for gid, gcfg in config.get("scan_groups", {}).items():
            group_meta[gid] = {"label": gcfg.get("label", gid), "track": gcfg.get("track", "")}

    # 按 group_id 归类
    flat = store.to_flat_items(records)
    groups_items = defaultdict(list)
    for item in flat:
        gid = item.get("_group_id", "unknown")
        groups_items[gid].append(item)

    # 逐组分析
    analyses = {}
    for gid, items in groups_items.items():
        meta = group_meta.get(gid, {})
        analysis = analyze_group(
            gid, items,
            label=meta.get("label", gid),
            track=meta.get("track", ""),
        )
        analyses[gid] = analysis
        logger.info(
            f"[{analysis.label}] "
            f"商品:{analysis.total_items} "
            f"卖家:{analysis.unique_sellers} "
            f"中位价:¥{analysis.price_median} "
            f"可行性:{analysis.viability_score}/100"
        )

    # 排名
    viability_rank = sorted(analyses.values(), key=lambda a: a.viability_score, reverse=True)
    demand_rank = sorted(analyses.values(), key=lambda a: a.demand_score, reverse=True)
    profit_rank = sorted(analyses.values(), key=lambda a: a.profit_score, reverse=True)

    result = {
        "summary": {
            "total_items": len(flat),
            "total_groups": len(analyses),
            "scan_data_dir": data_dir,
        },
        "groups": {gid: a.to_dict() for gid, a in analyses.items()},
        "rankings": {
            "by_viability": [{"group_id": a.group_id, "label": a.label, "score": a.viability_score} for a in viability_rank],
            "by_demand": [{"group_id": a.group_id, "label": a.label, "score": a.demand_score} for a in demand_rank],
            "by_profit": [{"group_id": a.group_id, "label": a.label, "score": a.profit_score} for a in profit_rank],
        },
    }

    # 保存分析结果
    out_path = Path(data_dir) / "_analysis_result.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(f"\n分析结果已保存: {out_path}")

    return result


def main():
    parser = argparse.ArgumentParser(description="闲鱼市场数据分析器")
    parser.add_argument("--data", default="data/", help="数据目录")
    parser.add_argument("--config", default="config/keywords.json", help="关键词配置（用于获取标签）")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    setup_logging(logging.DEBUG if args.verbose else logging.INFO)
    result = run_analysis(args.data, args.config)

    # 打印摘要
    print("\n" + "=" * 70)
    print("  闲鱼虚拟商品市场分析 · 变现可行性排名")
    print("=" * 70)
    for i, r in enumerate(result.get("rankings", {}).get("by_viability", []), 1):
        bar = "█" * int(r["score"] / 5)
        print(f"  {i}. {r['label']:<20} {r['score']:>5.1f}/100  {bar}")
    print("=" * 70)


if __name__ == "__main__":
    main()
