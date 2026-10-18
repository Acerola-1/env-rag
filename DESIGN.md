---
version: alpha
name: 环境知识库
description: 面向中文法规资料查询的本机授权工具，保持既有简洁表单与可核对来源。
colors:
  primary: "#135c8c"
  background: "#f7f8fa"
  panel: "#ffffff"
  ink: "#1c2024"
  muted: "#5b6570"
  line: "#d8dee4"
  danger: "#9d1f1f"
  warning: "#8a5300"
typography:
  sans:
    fontFamily: '-apple-system, "Segoe UI", "Noto Sans SC", sans-serif'
rounded:
  DEFAULT: "8px"
  panel: "10px"
spacing:
  page-max: "960px"
  panel-gap: "14px"
components:
  button: {}
  input: {}
  panel: {}
---

# 环境知识库 Design System

## Overview

### Creative North Star
法规资料工作台：先选择企业与资料库，再查询、核对证据与来源。

### Product context and register
中文学习与研究工具；以 OpenSpec 知识库权限契约、WORKSPACE-ACCESS.md 为依据。
桌面优先并兼容窄屏，产品表单而非营销页面。未声明日本市场或日本语言支持。
保持既有蓝色强调、轻边框与原文证据块，不进行视觉重塑。

## Colors
运行时唯一来源为 src/env_rag_final/access/static/style.css 的 :root 与深色媒体查询。
本文记录该文件已有语义，不生成第二套颜色。警告与错误同时提供文字。

## Typography
系统中文字体与 15px/1.6 正文；标题通过字号及字重区分。原文长段允许换行。

## Layout
最大宽度 960px，页面内边距 16px，面板间隔 14px。480px 以下表单纵排。
原文证据块限制高度并可滚动；状态区保留最小高度。问题属于私有输入，不写入地址栏。

## Elevation & Depth
使用边框和面板底色分区，不引入阴影与浮层。

## Shapes
控件圆角 8px，面板圆角 10px；映射见既有 CSS。

## Components
共享表单、按钮、状态文字与列表均由 access/static/index.html、app.js 和 style.css 维护。
企业、路由与模式下拉使用系统原生 select，接受操作系统弹窗几何与键盘行为。
不引入 UI 框架。登录、查询和切企业须有可理解的等待、失败和重试反馈。

## Motion
无装饰动画；旧请求由作用域与请求代次过滤，减少动态内容对阅读的影响。

## Accessibility
控件有中文标签、可见焦点与原生键盘行为；状态使用 live region。
不得把颜色作为唯一状态依据。口令默认隐藏，不写入页面持久存储。

## Content
权限不足不暴露其他资料库内容；完整性未知与接口成功分别表达。
状态使用中文，并提供重新选择企业、重新登录或稍后重试的具体指引。
