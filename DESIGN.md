---
version: alpha
name: "环境知识库 · 检索对照台"
description: "像翻开两本标准对读：问题固定、证据可查、差异可见。"
colors:
  primary: "#1d6356"
  background: "#f4f3ee"
  surface: "#ffffff"
  text: "#263a35"
  muted: "#5f706a"
  border: "#d7dfd8"
  accent: "#c6e3d3"
  warning: "#8b5719"
  danger: "#a33737"
typography:
  sans:
    fontFamily: "-apple-system, BlinkMacSystemFont, PingFang SC, Microsoft YaHei, sans-serif"
  serif:
    fontFamily: "Iowan Old Style, Songti SC, STSong, serif"
  mono:
    fontFamily: "SFMono-Regular, Menlo, monospace"
rounded:
  DEFAULT: "0.5rem"
  lg: "1rem"
spacing:
  section: "1.5rem"
  control: "0.75rem"
components:
  button:
    height: "2.75rem"
  evidence:
    height: "30rem"
---

# 环境知识库检索对照台

## Overview
中文、桌面优先、私有本机研究工具。参考标准审阅桌与并排校样：左侧安静的策略目录，右侧固定题目，下方并排答案与证据。独特元素是每份结果的纵向来源轨迹，帮助用户辨认 PG、图谱和共同来源。不用营销大标题、渐变或满屏仪表盘。

## Colors
上面的色值是规范。运行时映射到 `src/env_rag_final/web/static/style.css` 的同名 `--color-*`，组件仅消费变量。主色用于选中和主操作；warning/danger 都配文本，不能仅靠颜色辨认失败。

## Typography
普通控件采用系统中文无衬线；标题克制使用宋体；记录ID使用等宽字体。正文16px/1.7，长原文允许自然换行。

## Layout
左侧 250px 策略栏，主内容流自然页面滚动。结果列最小 360px，多策略横向可滚；移动端改为单列。原文面板拥有自己的30rem滚动上限；页壳不锁视口高度。

## Elevation & Depth
边线和纸面底色区分层级，无持续卡片阴影。焦点环清晰可见。

## Shapes
控件8px，主要内容容器16px。按钮高度稳定，加载时不扩大。

## Components
原生checkbox用于多策略、原生select用于澄清文档（接受系统弹出框）。所有点击用button/link；来源展开用details。共享状态、错误、空态和来源组件由app.js所有卡片共用。问题框与执行按钮是唯一提交入口，无键入即请求。

## Do's and Don'ts
完整清单独立于模型摘要；不能将 retrieved 或 HTTP200 写成“答案正确”。在同卡片引用定位原文，长文本不省略成伪全文。无旧结果复用伪现场。未知来源明确不可用，不猜页码。

## 问答与对照的入口分离（2026-10-10）
保留既有纸面绿与来源轨迹。使用方式采用原生 radio 分段选择：默认普通问答；路线采用四张互斥选择卡，LightRAG 模式用既有原生 select。对照实验才出现多选，默认 local 与 PG+local，并显示实际路线数、结果数和生成上限。路线确认条是本轮清晰度重点，不改变色值或结果证据组件。窄屏选择卡可两列，极窄屏恢复单列。
