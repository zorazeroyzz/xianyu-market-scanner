"""
工具函数：请求封装、User-Agent 轮转、解析器
闲鱼 H5 公开搜索接口 — 无需登录/Cookie
"""
import os
import json
import time
import random
import hashlib
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import quote

import requests
from fake_useragent import UserAgent

logger = logging.getLogger("xianyu-scanner")


# ────────────────────────── HTTP 客户端 ──────────────────────────

class XianyuClient:
    """
    闲鱼公开搜索接口封装 — 无需登录

    策略说明：
    1. 主通道：闲鱼 H5 搜索页面直接抓取（SSR 渲染，HTML 内嵌 JSON）
    2. 备用通道：goofish 公开 API（部分接口无需鉴权）
    3. 兜底通道：通过搜索引擎 site:goofish.com 间接采集
    """

    # H5 搜索页（SSR，HTML 内含商品 JSON 数据）
    H5_SEARCH_URL = "https://h5.m.goofish.com/search?keyword={keyword}&spm=a21ybx.search.result.0&page={page}"

    # 公开 AJAX 搜索接口（部分场景可直接访问）
    AJAX_SEARCH_URL = "https://h5api.m.goofish.com/h5/mtop.taobao.idlemtopsearch.pc.search/1.0/"

    def __init__(self, proxy_pool: Optional[list] = None):
        self.proxy_pool = proxy_pool or []
        self.ua = UserAgent(browsers=["chrome", "edge", "safari"], os=["windows", "macos", "android", "ios"])
        self.session = requests.Session()
        self._request_count = 0
        self._last_request_time = 0

    def _get_headers(self) -> dict:
        """构造合理的浏览器请求头"""
        return {
            "User-Agent": self.ua.random,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        }

    def _get_json_headers(self) -> dict:
        return {
            "User-Agent": self.ua.random,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Referer": "https://www.goofish.com/",
            "Origin": "https://www.goofish.com",
        }

    def _get_proxy(self) -> Optional[dict]:
        if not self.proxy_pool:
            return None
        proxy = random.choice(self.proxy_pool)
        return {"http": proxy, "https": proxy}

    def _throttle(self, delay_range: tuple = (2, 5)):
        """请求节流：随机延迟"""
        elapsed = time.time() - self._last_request_time
        min_delay = delay_range[0]
        if elapsed < min_delay:
            time.sleep(min_delay - elapsed)
        jitter = random.uniform(delay_range[0], delay_range[1])
        time.sleep(jitter)
        self._last_request_time = time.time()

    def search(self, keyword: str, page: int = 1, page_size: int = 20) -> dict:
        """
        执行闲鱼搜索（无需登录）

        尝试顺序：
        1. PC 版搜索页面（SSR HTML 内嵌数据）
        2. H5 搜索页面
        3. 公开 AJAX 接口

        返回:
        {
            "success": bool,
            "items": [...],
            "total": int,
            "source": str  # 数据来源标识
        }
        """
        # 尝试 PC 版搜索（goofish.com 无登录可搜）
        result = self._search_pc_web(keyword, page)
        if result["success"] and result["items"]:
            return result

        # 尝试 H5 页面抓取
        result = self._search_h5_ssr(keyword, page)
        if result["success"] and result["items"]:
            return result

        # 尝试 AJAX 接口
        result = self._search_ajax(keyword, page, page_size)
        return result

    def _search_pc_web(self, keyword: str, page: int = 1) -> dict:
        """通过 PC 版 goofish.com 搜索页抓取（公开访问）"""
        self._throttle()

        url = f"https://www.goofish.com/search?keyword={quote(keyword)}&page={page}"

        try:
            resp = self.session.get(
                url,
                headers=self._get_headers(),
                proxies=self._get_proxy(),
                timeout=15,
            )
            self._request_count += 1

            if resp.status_code != 200:
                logger.debug(f"PC 搜索返回 HTTP {resp.status_code}")
                return {"success": False, "items": [], "total": 0, "source": "pc_web"}

            items = self._parse_html_items(resp.text)
            return {
                "success": len(items) > 0,
                "items": items,
                "total": len(items),
                "source": "pc_web",
            }

        except requests.RequestException as e:
            logger.debug(f"PC 搜索异常: {e}")
            return {"success": False, "items": [], "total": 0, "source": "pc_web", "error": str(e)}

    def _search_h5_ssr(self, keyword: str, page: int = 1) -> dict:
        """通过 H5 搜索页 SSR 数据抓取"""
        self._throttle()

        url = self.H5_SEARCH_URL.format(keyword=quote(keyword), page=page)

        try:
            headers = self._get_headers()
            headers["User-Agent"] = self.ua["google chrome"]  # 模拟移动端
            resp = self.session.get(
                url,
                headers=headers,
                proxies=self._get_proxy(),
                timeout=15,
            )
            self._request_count += 1

            if resp.status_code != 200:
                return {"success": False, "items": [], "total": 0, "source": "h5_ssr"}

            items = self._parse_html_items(resp.text)
            return {
                "success": len(items) > 0,
                "items": items,
                "total": len(items),
                "source": "h5_ssr",
            }

        except requests.RequestException as e:
            logger.debug(f"H5 SSR 异常: {e}")
            return {"success": False, "items": [], "total": 0, "source": "h5_ssr", "error": str(e)}

    def _search_ajax(self, keyword: str, page: int = 1, page_size: int = 20) -> dict:
        """通过公开 AJAX 接口搜索"""
        self._throttle()

        params = {
            "jsv": "2.7.2",
            "appKey": "12574478",
            "api": "mtop.taobao.idlemtopsearch.pc.search",
            "v": "1.0",
            "timeout": "20000",
            "type": "jsonp",
            "dataType": "jsonp",
            "callback": f"mtopjsonp{random.randint(1,9)}",
        }

        data = {
            "keyword": keyword,
            "pageNumber": str(page),
            "pageSize": str(page_size),
        }

        try:
            resp = self.session.get(
                self.AJAX_SEARCH_URL,
                params={**params, "data": json.dumps(data, ensure_ascii=False)},
                headers=self._get_json_headers(),
                proxies=self._get_proxy(),
                timeout=15,
            )
            self._request_count += 1

            if resp.status_code != 200:
                return {"success": False, "items": [], "total": 0, "source": "ajax"}

            # 解析 JSONP
            text = resp.text
            json_match = re.search(r'\((\{.*\})\)', text, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group(1))
                items = self._extract_api_items(data)
                return {
                    "success": len(items) > 0,
                    "items": items,
                    "total": len(items),
                    "source": "ajax",
                }

            return {"success": False, "items": [], "total": 0, "source": "ajax", "error": "无法解析 JSONP"}

        except (requests.RequestException, json.JSONDecodeError) as e:
            logger.debug(f"AJAX 异常: {e}")
            return {"success": False, "items": [], "total": 0, "source": "ajax", "error": str(e)}

    def _parse_html_items(self, html: str) -> list:
        """
        从 SSR HTML 中提取商品数据

        闲鱼页面通常在 <script> 中嵌入 __INITIAL_STATE__ 或 window.__data__ JSON
        """
        items = []

        # 尝试提取 __INITIAL_STATE__
        patterns = [
            r'window\.__INITIAL_STATE__\s*=\s*(\{.*?\});?\s*</script>',
            r'window\.__NEXT_DATA__\s*=\s*(\{.*?\});?\s*</script>',
            r'window\.__data__\s*=\s*(\{.*?\});?\s*</script>',
            r'"resultList"\s*:\s*(\[.*?\])\s*[,}]',
            r'"itemList"\s*:\s*(\[.*?\])\s*[,}]',
        ]

        for pattern in patterns:
            match = re.search(pattern, html, re.DOTALL)
            if match:
                try:
                    data = json.loads(match.group(1))
                    items = self._walk_and_extract(data)
                    if items:
                        break
                except json.JSONDecodeError:
                    continue

        # 兜底：用正则直接提取价格和标题
        if not items:
            items = self._regex_extract(html)

        return items

    def _walk_and_extract(self, data, depth=0) -> list:
        """递归遍历 JSON 结构，找到商品列表"""
        if depth > 8:
            return []

        items = []

        if isinstance(data, list):
            for entry in data:
                if isinstance(entry, dict) and any(k in entry for k in ["itemId", "title", "price", "soldPrice"]):
                    item = self._normalize_item(entry)
                    if item.get("title"):
                        items.append(item)
                else:
                    items.extend(self._walk_and_extract(entry, depth + 1))

        elif isinstance(data, dict):
            # 检查当前层是否是商品
            if "itemId" in data and "title" in data:
                item = self._normalize_item(data)
                if item.get("title"):
                    return [item]

            # 搜索可能包含列表的 key
            list_keys = ["resultList", "itemList", "items", "list", "data", "props", "pageProps", "searchResult"]
            for key in list_keys:
                if key in data:
                    found = self._walk_and_extract(data[key], depth + 1)
                    if found:
                        items.extend(found)

            # 如果没找到，遍历所有值
            if not items:
                for v in data.values():
                    if isinstance(v, (dict, list)):
                        found = self._walk_and_extract(v, depth + 1)
                        if found:
                            items.extend(found)
                            break  # 找到第一个有效列表就停

        return items

    def _regex_extract(self, html: str) -> list:
        """兜底方案：用正则从 HTML 中提取商品信息"""
        items = []

        # 匹配商品卡片模式：标题 + 价格
        title_price_pairs = re.findall(
            r'title["\']?\s*[:=]\s*["\']([^"\']{4,80})["\'].*?'
            r'(?:price|soldPrice)["\']?\s*[:=]\s*["\']?(\d+\.?\d*)',
            html, re.DOTALL
        )

        for title, price in title_price_pairs:
            # 过滤明显非商品标题
            if any(skip in title.lower() for skip in ["script", "style", "function", "var ", "const "]):
                continue
            items.append({
                "id": hashlib.md5(title.encode()).hexdigest()[:12],
                "title": title.strip(),
                "price": self._safe_float(price),
                "original_price": 0,
                "sold_count": 0,
                "want_count": 0,
                "view_count": 0,
                "seller_id": "",
                "seller_name": "",
                "seller_credit": "",
                "location": "",
                "image_url": "",
                "detail_url": "",
                "publish_time": "",
                "scraped_at": datetime.now().isoformat(),
            })

        return items

    def _normalize_item(self, raw: dict) -> dict:
        """将各种格式的原始数据统一为标准商品结构"""
        item_id = str(raw.get("itemId", raw.get("id", raw.get("item_id", ""))))
        return {
            "id": item_id,
            "title": raw.get("title", raw.get("item_title", "")),
            "price": self._safe_float(raw.get("price", raw.get("soldPrice", raw.get("sold_price", "0")))),
            "original_price": self._safe_float(raw.get("originalPrice", raw.get("original_price", "0"))),
            "sold_count": self._safe_int(raw.get("soldCount", raw.get("sold_count", raw.get("commentCount", "0")))),
            "want_count": self._safe_int(raw.get("wantCount", raw.get("want_count", raw.get("likeCount", "0")))),
            "view_count": self._safe_int(raw.get("viewCount", raw.get("view_count", "0"))),
            "seller_id": str(raw.get("sellerId", raw.get("userId", raw.get("seller_id", "")))),
            "seller_name": raw.get("sellerNick", raw.get("nick", raw.get("seller_name", ""))),
            "seller_credit": str(raw.get("sellerCredit", raw.get("credit", ""))),
            "location": raw.get("area", raw.get("divisionName", raw.get("location", ""))),
            "image_url": raw.get("picUrl", raw.get("mainPic", raw.get("pic_url", ""))),
            "detail_url": f"https://www.goofish.com/item?id={item_id}" if item_id else "",
            "publish_time": raw.get("publishTime", raw.get("publish_time", "")),
            "scraped_at": datetime.now().isoformat(),
        }

    def _extract_api_items(self, data: dict) -> list:
        """从 AJAX API 响应中提取商品"""
        return self._walk_and_extract(data.get("data", data))

    @staticmethod
    def _safe_float(val) -> float:
        try:
            return float(str(val).replace(",", "").replace("¥", "").replace("元", ""))
        except (ValueError, TypeError):
            return 0.0

    @staticmethod
    def _safe_int(val) -> int:
        try:
            s = str(val).replace(",", "").replace("+", "").replace("万", "0000")
            return int(float(s))
        except (ValueError, TypeError):
            return 0


# ────────────────────────── 数据存储 ──────────────────────────

class DataStore:
    """将采集结果持久化为 JSON"""

    def __init__(self, data_dir: str = "data"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def save_items(self, group_id: str, keyword: str, items: list):
        """保存单次搜索结果"""
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_kw = hashlib.md5(keyword.encode()).hexdigest()[:8]
        filename = f"{group_id}_{safe_kw}_{ts}.json"
        filepath = self.data_dir / filename

        record = {
            "group_id": group_id,
            "keyword": keyword,
            "scraped_at": datetime.now().isoformat(),
            "item_count": len(items),
            "items": items,
        }

        filepath.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info(f"已保存 {len(items)} 条记录 → {filepath}")

    def load_all(self) -> list:
        """加载所有已采集的数据"""
        all_records = []
        for f in sorted(self.data_dir.glob("*.json")):
            if f.name.startswith("_"):
                continue  # 跳过分析结果文件
            try:
                record = json.loads(f.read_text(encoding="utf-8"))
                all_records.append(record)
            except json.JSONDecodeError:
                logger.warning(f"跳过损坏文件: {f}")
        return all_records

    def to_flat_items(self, records: Optional[list] = None) -> list:
        """将嵌套记录展平为单一商品列表"""
        if records is None:
            records = self.load_all()
        flat = []
        for rec in records:
            group_id = rec.get("group_id", "unknown")
            keyword = rec.get("keyword", "")
            for item in rec.get("items", []):
                item["_group_id"] = group_id
                item["_keyword"] = keyword
                flat.append(item)
        return flat


# ────────────────────────── 日志配置 ──────────────────────────

def setup_logging(level=logging.INFO):
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )
