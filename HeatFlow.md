# HeatFlow —— A股情绪热度引擎（Douyin版）

版本：v1.0 MVP
作者：Codex
目标平台：Windows + Python 本地环境 + 浏览器
目标用户：A股资讯复盘类抖音博主
开发周期：7~10天（MVP）

---

# 一、产品定位

## 1.1 产品名称

**HeatFlow —— A股情绪热度引擎**

## 1.2 产品使命

每天自动监测A股市场热点变化，实时统计全网热度，自动生成：

* Top10热股榜
* 热度变化动图（GIF/MP4）
* 炒作逻辑
* 情绪周期判断
* 抖音发布文案
* 历史数据库

最终实现：

**每天15:10之前，一键获得可直接发布到抖音的视频素材与文案。**

---

# 二、产品目标

## 2.1 核心目标

替代人工复盘流程：

人工流程：

收集资讯
→ 看热榜
→ 整理逻辑
→ 截图
→ 做图
→ 写文案
→ 发抖音

HeatFlow：

自动完成全部流程

## 2.2 成功指标

### 每日输出

* Top10热股榜
* 热度排行榜
* 主线板块
* 情绪阶段
* 热度GIF
* 竖屏MP4
* 抖音文案

### 系统性能

* 每3分钟采集一次
* 全天约110帧
* 收盘后5分钟内完成全部生成
* 数据自动入库

---

# 三、功能需求（PRD）

## 3.1 实时热度监测

### 功能描述

系统在交易时间内：

09:30–15:00

每3分钟执行一次采集。

### 数据来源

同花顺热股榜
东方财富人气榜
雪球热榜
财联社快讯
新浪财经
证券时报
微博财经热搜（可选）

### 输出

每次采集：

timestamp
stock_code
stock_name
heat_score
rank
price_change
board

保存至SQLite。

---

## 3.2 综合热度计算

### HeatScore模型

HeatScore =
0.30 × THS
+0.25 × EastMoney
+0.20 × Xueqiu
+0.15 × CLS
+0.10 × News

### 热度变化率

DeltaHeat = Heat_t - Heat_(t-1)

FinalScore =
0.7 × HeatScore
+0.3 × DeltaHeat

### 排名

系统实时生成：

Top10热股

---

## 3.3 热度排行榜网页

### 页面

首页

显示：

当前时间

Top10榜单

热度曲线

板块占比

主线标签

### 自动刷新

3分钟刷新一次。

---

## 3.4 帧保存

每次采集后：

生成排行榜图片：

1080×1920

命名：

frames/
2026-08-01_09-30.png

全天约110张。

---

## 3.5 GIF/MP4生成

收盘后：

读取全部帧

合成：

top10_heat.gif

top10_heat.mp4

时长：

20~30秒

用于：

抖音
视频号
小红书

---

## 3.6 炒作逻辑提取

### 输入

新闻

快讯

板块涨幅

涨停股

### 输出

示例：

AI算力方向全天持续强化，
光模块板块领涨，
中际旭创获资金集中关注，
市场围绕CPO产业链展开强化。

### 方法

规则 + GPT生成

---

## 3.7 情绪周期判断

系统自动输出：

启动期
发酵期
高潮期
分歧期
修复期
退潮期

### 指标

涨停家数

炸板率

连板高度

红盘比例

成交额

主线集中度

---

## 3.8 主线板块识别

输出：

AI算力
42%

机器人
18%

半导体
15%

消费
8%

其他
17%

---

## 3.9 龙头梯队

输出：

空间龙

情绪龙

容量龙

趋势龙

补涨龙

---

## 3.10 抖音文案生成

自动生成：

标题

正文

标签

示例：

今日A股热度TOP10出炉。

真正的主线仍是AI算力。

中际旭创全天热度第一，
寒武纪、工业富联持续强化。

一句话总结：

情绪未退，
主线仍在算力。

明天重点关注：

中际旭创是否继续放量

AI算力能否带动创业板

关注我，每天15:10看懂市场热点。

---

## 3.11 发布提醒

15:08

自动提醒：

微信

邮件

Windows通知

内容：

今日抖音素材已生成，可发布。

---

# 四、系统架构

HeatFlow

├── Data Collector
├── Heat Engine
├── Topic Engine
├── Sentiment Engine
├── Visual Engine
├── Report Engine
├── Database
├── Scheduler
└── Web Dashboard

---

# 五、技术选型

Python 3.11

Playwright

Requests

BeautifulSoup

Pandas

SQLite

APScheduler

Matplotlib

ImageIO

Pillow

Flask

Jinja2

FFmpeg

---

# 六、项目目录

heatflow/

├── app.py
├── config.yaml
├── requirements.txt
├── README.md
├── data/
│   ├── heat.db
│   ├── frames/
│   ├── gifs/
│   ├── videos/
│   └── reports/
├── collectors/
│   ├── ths.py
│   ├── eastmoney.py
│   ├── xueqiu.py
│   ├── cls.py
│   ├── news.py
│   └── merger.py
├── engine/
│   ├── heat_score.py
│   ├── topic_extract.py
│   ├── logic_generate.py
│   ├── sentiment.py
│   └── leaderboard.py
├── visual/
│   ├── frame_render.py
│   ├── gif_render.py
│   ├── video_render.py
│   └── dashboard.py
├── report/
│   ├── douyin_copy.py
│   ├── markdown.py
│   ├── html.py
│   └── exporter.py
├── scheduler/
│   ├── jobs.py
│   └── reminder.py
├── web/
│   ├── templates/
│   ├── static/
│   └── routes.py
└── tests/

---

# 七、数据库设计

## stocks

code
TEXT PRIMARY KEY

name
TEXT

board
TEXT

## heat_records

id
INTEGER

timestamp
DATETIME

code
TEXT

heat_score
REAL

rank
INTEGER

price_change
REAL

board
TEXT

## daily_reports

date
DATE PRIMARY KEY

top10_json
TEXT

main_theme
TEXT

sentiment_stage
TEXT

logic_text
TEXT

douyin_copy
TEXT

gif_path
TEXT

video_path
TEXT

created_at
DATETIME

---

# 八、热度算法

## 排名得分

score = 100 - rank

## 综合得分

H =
0.30×THS
+0.25×EM
+0.20×XQ
+0.15×CLS
+0.10×NEWS

## 动量

Delta =
H(t)-H(t-1)

## 最终

Final =
0.7H+0.3Delta

---

# 九、调度流程

09:30

启动采集

09:30–15:00

每3分钟：

采集

计算

保存

渲染

15:00

停止采集

15:02

Top10

15:04

主线

15:05

情绪

15:06

GIF

15:07

MP4

15:08

文案

15:09

数据库

15:10

提醒

---

# 十、网页Dashboard

## 首页

当前时间

Top10排行榜

热度变化曲线

主线板块

情绪阶段

GIF预览

## 历史页

日期选择

查看历史Top10

查看热度曲线

查看文案

下载GIF

---

# 十一、GIF设计

尺寸：

1080×1920

内容：

日期

时间

Top10

热度条

板块

主线标签

右侧：

热度曲线

每3分钟一帧。

---

# 十二、视频模板

片头：

今日A股热度TOP10

主体：

排行榜滚动

热度变化

主线板块

片尾：

关注我，每天15:10看懂市场热点

---

# 十三、开发计划

## Phase 1（MVP）

目标：

完成自动热度榜

任务：

数据采集

SQLite

热度算法

网页

帧保存

GIF

文案

提醒

预计：

3天

## Phase 2

目标：

真正可运营

新增：

主线识别

情绪周期

龙头梯队

历史查询

板块统计

预计：

4天

## Phase 3

目标：

内容工厂

新增：

自动配音

自动字幕

自动剪映模板

自动上传草稿

预计：

7天

---

# 十四、最终每日输出

2026-08-01/

├── top10_heat.gif
├── top10_heat.mp4
├── report.md
├── report.html
├── douyin_copy.txt
├── top10.csv
├── sentiment.json
└── leaderboard.png

每天15:10之前，以上全部自动生成。

---

# 十五、项目里程碑

M1

可以自动抓热榜

M2

可以生成Top10网页

M3

可以生成GIF

M4

可以自动写文案

M5

可以自动提醒发布

M6

可以识别主线

M7

可以判断情绪周期

M8

形成完整的抖音内容生产流水线

---

项目完成后，HeatFlow将成为一个本地运行的“A股内容生产引擎”，每天自动输出适合抖音发布的热点榜、动态图和文案，并持续积累历史数据库，为后续做AI分析、交易研究和账号矩阵运营提供基础设施。
