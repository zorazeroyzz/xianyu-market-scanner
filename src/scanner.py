"""
核心采集模块：按关键词组批量扫描闲鱼商品（无需登录）
"""
import json
import argparse
import logging
from pathlib import Path

from utils import XianyuClient, DataStore, setup_logging

logger = logging.getLogger("xianyu-scanner")


def load_config(config_path: str) -> dict:
    p = Path(config_path)
    if not p.exists():
        raise FileNotFoundError(f"配置文件不存在: {config_path}")
    return json.loads(p.read_text(encoding="utf-8"))


def run_scan(config_path: str, data_dir: str, groups_filter: list = None, proxy_file: str = None):
    """
    执行完整扫描流程（无需 Cookie）

    Args:
        config_path: 关键词配置文件路径
        data_dir: 数据存储目录
        groups_filter: 只扫描指定的 group_id 列表（None=全部）
        proxy_file: 可选的代理 IP 列表文件
    """
    config = load_config(config_path)
    scan_groups = config["scan_groups"]
    settings = config.get("settings", {})

    max_pages = settings.get("max_pages_per_keyword", 5)
    max_items = settings.get("max_items_per_keyword", 100)

    # 加载代理池（可选）
    proxy_pool = []
    if proxy_file:
        p = Path(proxy_file)
        if p.exists():
            proxy_pool = [line.strip() for line in p.read_text().splitlines() if line.strip() and not line.startswith("#")]
            logger.info(f"已加载 {len(proxy_pool)} 个代理")

    # 初始化
    client = XianyuClient(proxy_pool=proxy_pool)
    store = DataStore(data_dir)

    # 统计
    total_keywords = 0
    total_items = 0
    failed_keywords = []

    for group_id, group_cfg in scan_groups.items():
        if groups_filter and group_id not in groups_filter:
            continue

        label = group_cfg["label"]
        keywords = group_cfg["keywords"]
        track = group_cfg.get("track", "unknown")

        logger.info(f"\n{'='*60}")
        logger.info(f"扫描组: [{label}] (赛道: {track}, 关键词: {len(keywords)} 个)")
        logger.info(f"{'='*60}")

        for kw in keywords:
            total_keywords += 1
            logger.info(f"\n  >> 搜索: \"{kw}\"")

            all_items = []
            for page in range(1, max_pages + 1):
                if len(all_items) >= max_items:
                    break

                result = client.search(kw, page=page)

                if not result["success"]:
                    logger.warning(f"    第 {page} 页失败: {result.get('error', '无结果')}")
                    break

                items = result["items"]
                source = result.get("source", "unknown")

                if not items:
                    logger.info(f"    第 {page} 页无结果，停止翻页")
                    break

                all_items.extend(items)
                logger.info(f"    第 {page} 页: {len(items)} 条 (来源: {source}, 累计 {len(all_items)})")

                if len(items) < 10:
                    break

            if all_items:
                # 去重（按 id 或 title）
                seen = set()
                deduped = []
                for it in all_items:
                    key = it.get("id") or it.get("title", "")
                    if key and key not in seen:
                        seen.add(key)
                        deduped.append(it)

                deduped = deduped[:max_items]
                store.save_items(group_id, kw, deduped)
                total_items += len(deduped)
                logger.info(f"  ✓ \"{kw}\": {len(deduped)} 条 (去重后)")
            else:
                failed_keywords.append(kw)
                logger.warning(f"  ✗ \"{kw}\": 无数据")

    # 汇总
    logger.info(f"\n{'='*60}")
    logger.info(f"扫描完成!")
    logger.info(f"  关键词: {total_keywords}")
    logger.info(f"  商品总数: {total_items}")
    logger.info(f"  失败: {len(failed_keywords)}")
    logger.info(f"  请求次数: {client._request_count}")
    if failed_keywords:
        logger.info(f"  失败关键词: {failed_keywords}")
    logger.info(f"  数据目录: {data_dir}")
    logger.info(f"{'='*60}")


def main():
    parser = argparse.ArgumentParser(description="闲鱼市场数据采集器（无需登录）")
    parser.add_argument("--config", default="config/keywords.json", help="关键词配置文件")
    parser.add_argument("--data", default="data/", help="数据存储目录")
    parser.add_argument("--groups", nargs="*", help="只扫描指定 group_id（空格分隔）")
    parser.add_argument("--proxies", default=None, help="代理 IP 列表文件（可选，每行一个）")
    parser.add_argument("--verbose", action="store_true", help="详细日志")
    args = parser.parse_args()

    setup_logging(logging.DEBUG if args.verbose else logging.INFO)

    logger.info("闲鱼市场扫描器 v2.0 — 无需登录")
    logger.info("使用公开搜索接口采集数据")

    run_scan(args.config, args.data, args.groups, args.proxies)


if __name__ == "__main__":
    main()
