"""
工具函数：Playwright 浏览器采集、DOM 解析、数据存储
闲鱼搜索需要登录态，通过 Cookie 注入 + Playwright 无头浏览器实现
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

logger = logging.getLogger("xianyu-scanner")


# ────────────────────────── Cookie 管理 ──────────────────────────

class CookiePool:
    """从文件加载 Cookie 字符串，支持多 Cookie 轮转"""

    def __init__(self, cookie_file: str = "config/cookies.txt"):
        self.cookies = []
        self._index = 0
        p = Path(cookie_file)
        if p.exists():
            for line in p.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    self.cookies.append(line)
            logger.info(f"已加载 {len(self.cookies)} 个 Cookie")
        else:
            logger.warning(f"Cookie 文件不存在: {cookie_file}")

    @property
    def available(self) -> bool:
        return len(self.cookies) > 0

    def next(self) -> str:
        """轮转获取下一个 Cookie"""
        if not self.cookies:
            return ""
        cookie = self.cookies[self._index % len(self.cookies)]
        self._index += 1
        return cookie

    def to_playwright_cookies(self, cookie_str: str) -> list:
        """将 Cookie 字符串转换为 Playwright 格式"""
        pw_cookies = []
        for part in cookie_str.split(";"):
            part = part.strip()
            if "=" in part:
                name, _, value = part.partition("=")
                pw_cookies.append({
                    "name": name.strip(),
                    "value": value.strip(),
                    "domain": ".goofish.com",
                    "path": "/",
                })
        return pw_cookies


# ────────────────────────── 浏览器采集客户端 ──────────────────────────

class XianyuClient:
    """
    闲鱼搜索采集客户端 — 基于 Playwright + Cookie

    工作流程：
    1. 启动 Chromium 无头浏览器
    2. 注入用户提供的 Cookie（登录态）
    3. 访问搜索页，等待商品列表渲染
    4. 从 DOM 提取结构化商品数据
    """

    SEARCH_URL = "https://www.goofish.com/search?keyword={keyword}&spm=a21ybx.search.result.0"

    def __init__(self, cookie_pool: Optional[CookiePool] = None, proxy_pool: Optional[list] = None):
        self.cookie_pool = cookie_pool
        self.proxy_pool = proxy_pool or []
        self._request_count = 0
        self._last_request_time = 0
        self._browser = None
        self._context = None
        self._playwright = None

    def _ensure_browser(self):
        """懒加载浏览器实例"""
        if self._browser is not None:
            return

        from playwright.sync_api import sync_playwright
        self._playwright = sync_playwright().start()

        launch_args = {"headless": True}
        if self.proxy_pool:
            proxy = random.choice(self.proxy_pool)
            launch_args["proxy"] = {"server": proxy}

        self._browser = self._playwright.chromium.launch(**launch_args)
        self._context = self._browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 900},
            locale="zh-CN",
        )

        # 注入 Cookie
        if self.cookie_pool and self.cookie_pool.available:
            cookie_str = self.cookie_pool.next()
            pw_cookies = self.cookie_pool.to_playwright_cookies(cookie_str)
            if pw_cookies:
                self._context.add_cookies(pw_cookies)
                logger.info(f"已注入 {len(pw_cookies)} 个 Cookie 字段")

    def _throttle(self, delay_range: tuple = (2, 5)):
        """请求节流"""
        elapsed = time.time() - self._last_request_time
        min_delay = delay_range[0]
        if elapsed < min_delay:
            time.sleep(min_delay - elapsed)
        jitter = random.uniform(delay_range[0], delay_range[1])
        time.sleep(jitter)
        self._last_request_time = time.time()

    def search(self, keyword: str, page: int = 1, page_size: int = 20) -> dict:
        """
        执行闲鱼搜索

        返回:
        {
            "success": bool,
            "items": [...],
            "total": int,
            "source": str
        }
        """
        self._ensure_browser()
        self._throttle()

        url = self.SEARCH_URL.format(keyword=keyword)
        if page > 1:
            url += f"&page={page}"

        try:
            pw_page = self._context.new_page()
            self._request_count += 1

            # 导航到搜索页
            pw_page.goto(url, wait_until="domcontentloaded", timeout=30000)

            # 等待商品列表渲染（尝试多个可能的选择器）
            loaded = False
            for selector in [
                'a[href*="/item/"]',
                '[class*="feeds-item"]',
                '[class*="ItemCard"]',
                '[class*="search-content"]',
            ]:
                try:
                    pw_page.wait_for_selector(selector, timeout=8000)
                    loaded = True
                    break
                except:
                    continue

            if not loaded:
                # 检查是否遇到登录墙
                if self._check_login_wall(pw_page):
                    logger.warning("遇到登录墙 — Cookie 可能已过期，请更新 config/cookies.txt")
                    pw_page.close()
                    return {"success": False, "items": [], "total": 0, "source": "playwright",
                            "error": "需要登录，请更新 Cookie"}

                # 再等一会
                pw_page.wait_for_timeout(3000)

            # 关闭可能的弹窗
            self._dismiss_popups(pw_page)

            # 滚动页面加载更多
            self._scroll_page(pw_page)

            # 从 DOM 提取商品
            items = self._extract_items_from_dom(pw_page)

            pw_page.close()

            return {
                "success": len(items) > 0,
                "items": items,
                "total": len(items),
                "source": "playwright",
            }

        except Exception as e:
            logger.warning(f"Playwright 采集异常: {e}")
            try:
                pw_page.close()
            except:
                pass
            return {"success": False, "items": [], "total": 0, "source": "playwright", "error": str(e)}

    def _check_login_wall(self, pw_page) -> bool:
        """检查是否遇到登录弹窗"""
        try:
            login_indicators = pw_page.query_selector_all(
                '[class*="baxia-dialog"], [class*="login-dialog"], iframe[src*="login"]'
            )
            return len(login_indicators) > 0
        except:
            return False

    def _dismiss_popups(self, pw_page):
        """关闭弹窗/遮罩"""
        try:
            pw_page.evaluate("""() => {
                document.querySelectorAll('[class*="baxia"], [class*="login-dialog"], [class*="mask"]').forEach(el => el.remove());
                document.querySelectorAll('iframe[src*="login"]').forEach(el => el.remove());
            }""")
        except:
            pass

    def _scroll_page(self, pw_page, scrolls: int = 3):
        """滚动页面触发懒加载"""
        try:
            for _ in range(scrolls):
                pw_page.evaluate("window.scrollBy(0, 800)")
                pw_page.wait_for_timeout(800)
        except:
            pass

    def _extract_items_from_dom(self, pw_page) -> list:
        """从渲染后的 DOM 提取商品数据"""
        items = pw_page.evaluate("""() => {
            const results = [];
            const seen = new Set();

            // 查找所有商品链接
            const links = document.querySelectorAll('a[href*="/item/"]');
            links.forEach(link => {
                const href = link.getAttribute('href') || '';
                const match = href.match(/item[/?](?:id=)?(\\w+)/);
                const itemId = match ? match[1] : '';
                if (!itemId || seen.has(itemId)) return;
                seen.add(itemId);

                // 找到包含该链接的卡片容器
                const card = link.closest('[class*="feeds-item"]')
                           || link.closest('[class*="ItemCard"]')
                           || link.closest('[class*="item-card"]')
                           || link;

                const text = (card.textContent || '').replace(/\\s+/g, ' ').trim();

                // 提取价格（¥ 后面的数字）
                const priceMatch = text.match(/[¥￥](\\d+\\.?\\d*)/);
                const price = priceMatch ? parseFloat(priceMatch[1]) : 0;

                // 提取 "想要" 数
                const wantMatch = text.match(/(\\d+)\\s*人想要/);
                const wantCount = wantMatch ? parseInt(wantMatch[1]) : 0;

                // 提取标题（链接文本或卡片第一段有意义的文本）
                let title = '';
                const titleEl = card.querySelector('[class*="title"], [class*="Title"], h3, h4');
                if (titleEl) {
                    title = titleEl.textContent.trim();
                }
                if (!title) {
                    // 取卡片文本的前80个字符作为标题
                    title = text.substring(0, 80);
                }

                // 提取图片
                const img = card.querySelector('img[src*="alicdn"], img[src*="goofish"]');
                const imageUrl = img ? (img.getAttribute('src') || '') : '';

                // 提取卖家信息
                const sellerEl = card.querySelector('[class*="seller"], [class*="nick"], [class*="user"]');
                const sellerName = sellerEl ? sellerEl.textContent.trim() : '';

                if (title && title.length > 2) {
                    results.push({
                        id: itemId,
                        title: title.substring(0, 120),
                        price: price,
                        want_count: wantCount,
                        seller_name: sellerName.substring(0, 30),
                        image_url: imageUrl,
                        detail_url: 'https://www.goofish.com/item?id=' + itemId,
                    });
                }
            });

            return results;
        }""")

        # 补充字段并规范化
        normalized = []
        for raw in items:
            normalized.append({
                "id": raw.get("id", ""),
                "title": raw.get("title", ""),
                "price": float(raw.get("price", 0)),
                "original_price": 0,
                "sold_count": 0,
                "want_count": int(raw.get("want_count", 0)),
                "view_count": 0,
                "seller_id": "",
                "seller_name": raw.get("seller_name", ""),
                "seller_credit": "",
                "location": "",
                "image_url": raw.get("image_url", ""),
                "detail_url": raw.get("detail_url", ""),
                "publish_time": "",
                "scraped_at": datetime.now().isoformat(),
            })

        return normalized

    def close(self):
        """释放浏览器资源"""
        try:
            if self._context:
                self._context.close()
            if self._browser:
                self._browser.close()
            if self._playwright:
                self._playwright.stop()
        except:
            pass

    def __del__(self):
        self.close()


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
                continue
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
