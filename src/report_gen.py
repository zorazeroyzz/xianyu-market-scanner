"""
报告生成器：将分析结果渲染为交互式 HTML 报告
"""
import json
import argparse
import logging
from pathlib import Path
from datetime import datetime

from utils import setup_logging

logger = logging.getLogger("xianyu-scanner")

# ── HTML 模板（Neon Noir 风格，与主报告视觉一致）──

REPORT_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>闲鱼市场扫描报告</title>
<script src="https://cdn.tailwindcss.com"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/echarts/5.5.0/echarts.min.js"></script>
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+SC:wght@300;400;700;900&family=JetBrains+Mono:wght@300;400;700&display=swap" rel="stylesheet">
<style>
:root{--bg:#0a0c1a;--card:rgba(16,19,40,0.85);--green:#39ff85;--pink:#ff3cac;--cyan:#00e5ff;--orange:#ff9d2e;--purple:#b24dff;--text:#e8eaf0;--muted:#7a8199}
*{margin:0;padding:0;box-sizing:border-box}
body{background:var(--bg);color:var(--text);font-family:'Noto Sans SC','JetBrains Mono',sans-serif;line-height:1.75;overflow-x:hidden}
::selection{background:var(--green);color:var(--bg)}
::-webkit-scrollbar{width:5px}::-webkit-scrollbar-thumb{background:var(--green);border-radius:3px}
.mono{font-family:'JetBrains Mono',monospace}
.container{max-width:1200px;margin:0 auto;padding:2rem 1.5rem}
h1{font-size:clamp(1.8rem,4vw,2.8rem);font-weight:900;background:linear-gradient(135deg,var(--green),var(--cyan));-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;margin-bottom:0.5rem}
h2{font-size:1.4rem;font-weight:700;margin:2rem 0 1rem;padding-bottom:0.5rem;border-bottom:1px solid rgba(57,255,133,0.1)}
.subtitle{color:var(--muted);font-size:0.85rem;margin-bottom:2rem}
.card{background:var(--card);border:1px solid rgba(57,255,133,0.08);border-radius:12px;padding:1.5rem;margin-bottom:1rem;backdrop-filter:blur(10px);transition:all 0.3s}
.card:hover{border-color:rgba(57,255,133,0.2);transform:translateY(-2px);box-shadow:0 0 20px rgba(57,255,133,0.08)}
.score-bar{height:6px;border-radius:3px;background:rgba(57,255,133,0.1)}
.score-fill{height:100%;border-radius:3px;transition:width 0.8s ease}
.tag{display:inline-block;font-size:0.65rem;padding:2px 8px;border-radius:4px;border:1px solid;margin-right:4px}
.tag-green{color:var(--green);border-color:rgba(57,255,133,0.3);background:rgba(57,255,133,0.06)}
.tag-pink{color:var(--pink);border-color:rgba(255,60,172,0.3);background:rgba(255,60,172,0.06)}
.tag-cyan{color:var(--cyan);border-color:rgba(0,229,255,0.3);background:rgba(0,229,255,0.06)}
.tag-orange{color:var(--orange);border-color:rgba(255,157,46,0.3);background:rgba(255,157,46,0.06)}
.chart-box{width:100%;height:360px;border-radius:12px;background:var(--card);border:1px solid rgba(57,255,133,0.08);padding:0.5rem;margin:1rem 0}
.grid{display:grid;gap:1rem}
.grid-2{grid-template-columns:repeat(auto-fill,minmax(300px,1fr))}
.grid-4{grid-template-columns:repeat(auto-fill,minmax(160px,1fr))}
table{width:100%;border-collapse:collapse;font-size:0.85rem}
th{text-align:left;padding:8px 12px;color:var(--muted);font-weight:400;border-bottom:1px solid rgba(57,255,133,0.1)}
td{padding:8px 12px;border-bottom:1px solid rgba(57,255,133,0.04)}
.num{font-family:'JetBrains Mono',monospace;color:var(--green)}
.footer{text-align:center;padding:3rem;color:var(--muted);font-size:0.7rem;letter-spacing:0.1em}
</style>
</head>
<body>
<div class="container">
<h1>闲鱼市场扫描报告</h1>
<div class="subtitle mono">XIANYU MARKET SCAN · {{ generated_at }} · 采集商品: {{ total_items }} 条 · 赛道: {{ total_groups }} 个</div>

<!-- 概览统计 -->
<div class="grid grid-4" style="margin-bottom:2rem">
{{ summary_cards }}
</div>

<!-- 可行性排名图表 -->
<h2>变现可行性排名</h2>
<div class="chart-box" id="chart-rank"></div>

<!-- 价格分布图表 -->
<h2>各赛道价格分布</h2>
<div class="chart-box" id="chart-price"></div>

<!-- 需求 vs 竞争散点图 -->
<h2>需求-竞争矩阵</h2>
<div class="chart-box" id="chart-matrix"></div>

<!-- 各组详情 -->
<h2>赛道详细分析</h2>
{{ group_details }}

</div>

<div class="footer">
XIANYU MARKET SCANNER · DATA-DRIVEN COMMERCIALIZATION ANALYSIS<br>
本报告基于闲鱼公开搜索数据生成，仅供市场调研参考
</div>

<script>
const EC_FONT='JetBrains Mono,Noto Sans SC,sans-serif';
const C={green:'#39ff85',pink:'#ff3cac',cyan:'#00e5ff',orange:'#ff9d2e',purple:'#b24dff'};
const DATA = {{ analysis_json }};

function init(id,opt){
  const d=document.getElementById(id);if(!d)return;
  const c=echarts.init(d,null,{renderer:'svg'});c.setOption(opt);
  window.addEventListener('resize',()=>c.resize());
}

// 可行性排名
const rankData = DATA.rankings.by_viability || [];
init('chart-rank',{
  tooltip:{trigger:'axis',axisPointer:{type:'shadow'}},
  grid:{left:140,right:30,top:20,bottom:30},
  xAxis:{type:'value',max:100,axisLabel:{color:'#7a8199',fontFamily:EC_FONT,fontSize:10},splitLine:{lineStyle:{color:'rgba(57,255,133,0.05)'}},axisLine:{show:false}},
  yAxis:{type:'category',data:rankData.map(r=>r.label).reverse(),axisLabel:{color:'#e8eaf0',fontFamily:EC_FONT,fontSize:11},axisLine:{lineStyle:{color:'rgba(57,255,133,0.1)'}},axisTick:{show:false}},
  series:[{type:'bar',data:rankData.map(r=>r.score).reverse(),barWidth:16,
    itemStyle:{borderRadius:[0,4,4,0],color:function(p){const v=p.value;return v>70?C.green:v>50?C.cyan:v>30?C.orange:C.pink}},
    label:{show:true,position:'right',color:'#7a8199',fontFamily:EC_FONT,fontSize:10,formatter:p=>p.value.toFixed(1)}
  }]
});

// 价格分布
const groups = DATA.groups || {};
const gids = Object.keys(groups);
const colors = [C.green,C.pink,C.cyan,C.orange,C.purple,'#ff6b6b','#ffd93d','#6bcb77'];
init('chart-price',{
  tooltip:{trigger:'item'},
  legend:{bottom:5,textStyle:{color:'#7a8199',fontFamily:EC_FONT,fontSize:10}},
  grid:{left:60,right:30,top:30,bottom:50},
  xAxis:{type:'category',data:gids.map(g=>groups[g].label),axisLabel:{color:'#e8eaf0',fontFamily:EC_FONT,fontSize:10,rotate:20},axisLine:{lineStyle:{color:'rgba(57,255,133,0.1)'}}},
  yAxis:{type:'value',name:'¥',axisLabel:{color:'#7a8199',fontFamily:EC_FONT,fontSize:10},splitLine:{lineStyle:{color:'rgba(57,255,133,0.05)'}},axisLine:{show:false}},
  series:[
    {name:'P25',type:'bar',stack:'price',data:gids.map(g=>groups[g].price_p25),itemStyle:{color:'rgba(57,255,133,0.15)'},barWidth:30},
    {name:'中位价',type:'bar',stack:'price',data:gids.map(g=>groups[g].price_median-groups[g].price_p25),itemStyle:{color:'rgba(57,255,133,0.4)'}},
    {name:'P75',type:'bar',stack:'price',data:gids.map(g=>groups[g].price_p75-groups[g].price_median),itemStyle:{color:'rgba(0,229,255,0.3)'}},
    {name:'最高价',type:'scatter',data:gids.map(g=>groups[g].price_max),symbolSize:8,itemStyle:{color:C.orange}}
  ]
});

// 需求-竞争矩阵
init('chart-matrix',{
  tooltip:{formatter:function(p){return '<div style="background:rgba(10,12,26,0.95);border:1px solid rgba(57,255,133,0.2);border-radius:8px;padding:10px 14px;font-family:JetBrains Mono,sans-serif;font-size:12px;color:#e8eaf0"><strong style="color:#39ff85">'+p.data[3]+'</strong><br>需求:'+p.data[0]+' 竞争:'+p.data[1]+'<br>可行性:'+p.data[2]+'</div>'}},
  grid:{left:60,right:40,top:30,bottom:50},
  xAxis:{name:'需求评分',type:'value',min:0,max:100,axisLabel:{color:'#7a8199',fontFamily:EC_FONT,fontSize:10},splitLine:{lineStyle:{color:'rgba(57,255,133,0.05)'}},axisLine:{lineStyle:{color:'rgba(57,255,133,0.1)'}}},
  yAxis:{name:'竞争强度',type:'value',min:0,max:100,axisLabel:{color:'#7a8199',fontFamily:EC_FONT,fontSize:10},splitLine:{lineStyle:{color:'rgba(57,255,133,0.05)'}},axisLine:{lineStyle:{color:'rgba(57,255,133,0.1)'}}},
  series:[{type:'scatter',symbolSize:function(d){return Math.max(15,d[2]*0.4)},
    data:gids.map((g,i)=>[groups[g].demand_score,groups[g].competition_score,groups[g].viability_score,groups[g].label,colors[i%colors.length]]),
    itemStyle:{color:p=>p.data[4],shadowBlur:10,shadowColor:'rgba(57,255,133,0.2)'},
    label:{show:true,formatter:p=>p.data[3],position:'top',color:'#e8eaf0',fontFamily:EC_FONT,fontSize:10},
    markLine:{silent:true,lineStyle:{color:'rgba(57,255,133,0.15)',type:'dashed'},data:[{xAxis:50,label:{show:true,formatter:'需求分界',color:'#7a8199',fontSize:9}},{yAxis:50,label:{show:true,formatter:'竞争分界',color:'#7a8199',fontSize:9}}]}
  }]
});
</script>
</body>
</html>"""


def generate_report(analysis_path: str, output_dir: str):
    """从分析结果 JSON 生成 HTML 报告"""

    p = Path(analysis_path)
    if not p.exists():
        logger.error(f"分析结果文件不存在: {analysis_path}")
        logger.info("请先运行 analyzer.py 生成分析结果")
        return

    data = json.loads(p.read_text(encoding="utf-8"))
    groups = data.get("groups", {})

    # 概览卡片
    summary_cards = ""
    stats = [
        ("采集商品", str(data["summary"].get("total_items", 0)), "green"),
        ("扫描赛道", str(data["summary"].get("total_groups", 0)), "cyan"),
        ("最高可行性", f"{max((g['viability_score'] for g in groups.values()), default=0):.1f}", "pink"),
        ("最高中位价", f"¥{max((g['price_median'] for g in groups.values()), default=0):.0f}", "orange"),
    ]
    for label, value, color in stats:
        summary_cards += f'''<div class="card" style="text-align:center">
<div class="mono num" style="font-size:1.8rem;color:var(--{color})">{value}</div>
<div style="font-size:0.75rem;color:var(--muted);margin-top:4px">{label}</div></div>\n'''

    # 各组详情
    group_details = ""
    sorted_groups = sorted(groups.items(), key=lambda x: x[1]["viability_score"], reverse=True)

    for gid, g in sorted_groups:
        track_tag = {"game": "tag-pink", "infra": "tag-green", "visual": "tag-cyan"}.get(g.get("track", ""), "tag-orange")
        track_label = {"game": "游戏", "infra": "基础设施", "visual": "视觉/数字人"}.get(g.get("track", ""), g.get("track", ""))

        # 评分条
        def bar(score, color):
            return f'<div class="score-bar"><div class="score-fill" style="width:{score}%;background:var(--{color})"></div></div>'

        # 热门商品表
        top_items_html = ""
        for it in g.get("top_items_by_want", [])[:5]:
            top_items_html += f'<tr><td>{it["title"]}</td><td class="num">¥{it["price"]}</td><td class="num">{it["want_count"]}</td></tr>'

        # 头部卖家表
        top_sellers_html = ""
        for s in g.get("top_sellers", [])[:5]:
            top_sellers_html += f'<tr><td>{s["seller_name"]}</td><td class="num">{s["item_count"]}</td><td class="num">¥{s["avg_price"]}</td><td class="num">{s["total_sold"]}</td></tr>'

        # 关键词明细
        kw_html = ""
        for kw in g.get("keyword_breakdown", [])[:8]:
            kw_html += f'<tr><td>{kw["keyword"]}</td><td class="num">{kw["count"]}</td><td class="num">¥{kw["avg_price"]}</td><td class="num">{kw["max_want"]}</td></tr>'

        group_details += f'''
<div class="card" id="group-{gid}">
  <div style="display:flex;align-items:center;gap:8px;margin-bottom:1rem">
    <span class="tag {track_tag} mono">{track_label}</span>
    <span style="font-weight:700;font-size:1.1rem">{g["label"]}</span>
    <span class="mono" style="margin-left:auto;color:var(--green);font-size:1.2rem;font-weight:700">{g["viability_score"]:.1f}<span style="font-size:0.7rem;color:var(--muted)">/100</span></span>
  </div>

  <div class="grid grid-4" style="margin-bottom:1rem;font-size:0.8rem">
    <div><span style="color:var(--muted)">商品数</span><br><span class="mono num">{g["total_items"]}</span></div>
    <div><span style="color:var(--muted)">卖家数</span><br><span class="mono num">{g["unique_sellers"]}</span></div>
    <div><span style="color:var(--muted)">中位价</span><br><span class="mono num">¥{g["price_median"]}</span></div>
    <div><span style="color:var(--muted)">总销量</span><br><span class="mono num">{g["total_sold_estimate"]}</span></div>
  </div>

  <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:1rem;margin-bottom:1rem;font-size:0.78rem">
    <div><span style="color:var(--muted)">需求 {g["demand_score"]:.0f}</span>{bar(g["demand_score"], "green")}</div>
    <div><span style="color:var(--muted)">利润 {g["profit_score"]:.0f}</span>{bar(g["profit_score"], "cyan")}</div>
    <div><span style="color:var(--muted)">竞争 {g["competition_score"]:.0f}</span>{bar(g["competition_score"], "pink")}</div>
  </div>

  <details style="margin-top:0.5rem">
    <summary style="cursor:pointer;color:var(--muted);font-size:0.8rem;margin-bottom:0.5rem">展开详细数据 ▾</summary>

    <div class="grid grid-2" style="margin-top:1rem">
      <div>
        <div style="font-size:0.8rem;color:var(--muted);margin-bottom:0.5rem">热门商品 (按想要数)</div>
        <table><tr><th>标题</th><th>价格</th><th>想要</th></tr>{top_items_html}</table>
      </div>
      <div>
        <div style="font-size:0.8rem;color:var(--muted);margin-bottom:0.5rem">头部卖家</div>
        <table><tr><th>卖家</th><th>商品数</th><th>均价</th><th>销量</th></tr>{top_sellers_html}</table>
      </div>
    </div>

    <div style="margin-top:1rem">
      <div style="font-size:0.8rem;color:var(--muted);margin-bottom:0.5rem">关键词维度</div>
      <table><tr><th>关键词</th><th>商品数</th><th>均价</th><th>最高想要</th></tr>{kw_html}</table>
    </div>

    <div style="margin-top:1rem;font-size:0.78rem;color:var(--muted)">
      价格区间: ¥{g["price_min"]} ~ ¥{g["price_max"]} | P25: ¥{g["price_p25"]} | P75: ¥{g["price_p75"]} | 均价: ¥{g["price_mean"]}
    </div>
  </details>
</div>
'''

    # 渲染模板
    html = REPORT_TEMPLATE
    html = html.replace("{{ generated_at }}", datetime.now().strftime("%Y-%m-%d %H:%M"))
    html = html.replace("{{ total_items }}", str(data["summary"].get("total_items", 0)))
    html = html.replace("{{ total_groups }}", str(data["summary"].get("total_groups", 0)))
    html = html.replace("{{ summary_cards }}", summary_cards)
    html = html.replace("{{ group_details }}", group_details)
    html = html.replace("{{ analysis_json }}", json.dumps(data, ensure_ascii=False))

    # 写入文件
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"xianyu_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
    out_path.write_text(html, encoding="utf-8")
    logger.info(f"报告已生成: {out_path}")
    return str(out_path)


def main():
    parser = argparse.ArgumentParser(description="闲鱼市场扫描报告生成器")
    parser.add_argument("--data", default="data/_analysis_result.json", help="分析结果 JSON")
    parser.add_argument("--output", default="reports/", help="报告输出目录")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    setup_logging(logging.DEBUG if args.verbose else logging.INFO)
    generate_report(args.data, args.output)


if __name__ == "__main__":
    main()
