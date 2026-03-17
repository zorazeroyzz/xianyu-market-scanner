# 闲鱼虚拟商品市场扫描器 (Xianyu Market Scanner)

为「开源技术商业化嗅探报告」提供真实市场数据支撑。

## 功能

1. **数据采集** — 按关键词组批量抓取闲鱼商品数据（价格、销量、卖家信息），**无需登录**
2. **竞品分析** — 统计各赛道的竞争密度、价格区间、头部卖家
3. **需求热力图** — 基于 "想要" 数和搜索结果量评估真实需求
4. **变现可行性评分** — 综合价格/竞争/需求给出自动化评分
5. **报告生成** — 输出 HTML 可视化报告 + JSON 原始数据

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 运行采集（无需 Cookie，直接执行）
python src/scanner.py --config config/keywords.json

# 3. 仅分析已有数据
python src/analyzer.py --data data/

# 4. 生成报告
python src/report_gen.py --data data/ --output reports/
```

### 可选参数

```bash
# 只扫描指定赛道
python src/scanner.py --groups pokemon_trade mahjong_soul

# 使用代理 IP 池（每行一个代理地址）
python src/scanner.py --proxies config/proxies.txt

# 详细日志
python src/scanner.py --verbose
```

## 采集原理

扫描器**不依赖登录或 Cookie**，通过闲鱼公开的搜索页面获取数据：

| 通道 | URL | 方式 | 说明 |
|------|-----|------|------|
| PC Web | `s.goofish.com/search?keyword=...` | SSR HTML 解析 | 首选，内嵌 `__INITIAL_STATE__` JSON |
| H5 SSR | `h5.m.goofish.com/search?keyword=...` | SSR HTML 解析 | 备用，支持 `__NEXT_DATA__` 格式 |
| AJAX | `h5api.m.goofish.com/h5/mtop.taobao.idlemtopsearch.pc.search` | JSONP 解析 | 最后兜底 |

三通道自动 Fallback，确保高可用。

## 项目结构

```
xianyu-market-scanner/
├── config/
│   ├── keywords.json      # 关键词组配置（按赛道分组）
│   └── cookies.txt        # 已弃用（保留兼容，无需填入）
├── src/
│   ├── scanner.py         # 核心采集模块（无需登录）
│   ├── analyzer.py        # 数据分析模块
│   ├── report_gen.py      # 报告生成器
│   └── utils.py           # 工具函数（多通道请求、HTML解析、反反爬）
├── data/                  # 采集原始数据（JSON）
├── reports/               # 生成的分析报告
└── requirements.txt
```

## 反风控策略

- 随机 User-Agent（fake-useragent）
- 请求间隔抖动（2-5s 可配置）
- 单 IP 日请求量限制
- 多通道 Fallback（PC → H5 → AJAX）
- 可选：代理 IP 池轮转（`--proxies` 参数）

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
- 闲鱼前端结构可能变更，如采集失败请检查 `utils.py` 中的解析逻辑
