# 闲鱼虚拟商品市场扫描器 (Xianyu Market Scanner)

为「开源技术商业化嗅探报告」提供真实市场数据支撑。

## 功能

1. **数据采集** — 基于 Playwright 无头浏览器 + Cookie 注入，批量抓取闲鱼商品数据
2. **竞品分析** — 统计各赛道的竞争密度、价格区间、头部卖家
3. **需求热力图** — 基于 "想要" 数和搜索结果量评估真实需求
4. **变现可行性评分** — 综合价格/竞争/需求给出自动化评分
5. **报告生成** — 输出 HTML 可视化报告 + JSON 原始数据

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt
playwright install chromium

# 2. 配置 Cookie（必须）
# 登录 goofish.com → F12 → Cookie → 复制粘贴到 config/cookies.txt
# 详见下方「Cookie 获取」章节

# 3. 运行采集
python src/scanner.py --config config/keywords.json

# 4. 仅分析已有数据
python src/analyzer.py --data data/

# 5. 生成报告
python src/report_gen.py --data data/ --output reports/
```

### 可选参数

```bash
# 只扫描指定赛道
python src/scanner.py --groups pokemon_trade mahjong_soul

# 指定 Cookie 文件
python src/scanner.py --cookies config/cookies.txt

# 使用代理 IP 池
python src/scanner.py --proxies config/proxies.txt

# 详细日志
python src/scanner.py --verbose
```

## Cookie 获取

闲鱼搜索接口需要登录态。获取 Cookie 只需 3 步：

1. 浏览器打开 `https://www.goofish.com` 并登录
2. 按 `F12` → `Application` → `Cookies` → `www.goofish.com`
3. 复制关键字段（或 Network 面板中任意请求的 Cookie 头），粘贴到 `config/cookies.txt`

支持多 Cookie 轮转（每行一个），建议 2-3 个账号降低风控风险。Cookie 有效期约 24-48 小时。

## 采集原理

使用 **Playwright Chromium 无头浏览器**：

1. 启动 headless Chromium
2. 注入用户提供的 Cookie（恢复登录态）
3. 导航到 `www.goofish.com/search?keyword=...`
4. 等待商品列表 DOM 渲染完成
5. 通过 JavaScript 从 DOM 提取商品数据（标题、价格、想要数、卖家等）
6. 自动去重 + 持久化为 JSON

## 项目结构

```
xianyu-market-scanner/
├── config/
│   ├── keywords.json      # 关键词组配置（按赛道分组）
│   └── cookies.txt        # 闲鱼 Cookie 池（需自行填入）
├── src/
│   ├── scanner.py         # 核心采集模块
│   ├── analyzer.py        # 数据分析模块
│   ├── report_gen.py      # 报告生成器
│   └── utils.py           # Playwright 客户端、Cookie 管理、数据存储
├── data/                  # 采集原始数据（JSON）
├── reports/               # 生成的分析报告
└── requirements.txt
```

## 反风控策略

- Playwright 真实浏览器指纹（非 requests）
- 多 Cookie 轮转
- 请求间隔抖动（2-5s 可配置）
- 可选：代理 IP 池轮转（`--proxies` 参数）
- 自动检测登录墙并提醒更新 Cookie

## 评分体系

| 维度 | 权重 | 评估内容 |
|------|------|----------|
| 需求 (Demand) | 35% | 想要数、销量、商品密度 |
| 利润 (Profit) | 35% | 中位价格、高价空间、规模化潜力 |
| 竞争 (Competition) | 30% | 卖家数量、头部集中度、价格战信号 |

**综合可行性** = 需求×0.35 + 利润×0.35 + (100-竞争)×0.30

## 注意事项

- 仅供市场调研使用
- 请遵守闲鱼平台规则
- 不要高频率请求，合理设置延迟
- Cookie 过期后需重新获取
- 闲鱼前端结构可能变更，如采集失败请检查 `utils.py` 中的 DOM 提取逻辑
