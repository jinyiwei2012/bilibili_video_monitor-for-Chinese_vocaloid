
---

# 📺 Bilibili 视频播放量监控器

**支持多 BV 号实时监控 / 图表展示 / 自动推送（OneBot via NapCat）/ 自动封面保存 / 数据持久化（JSON + Excel）**

---

## ✨ 功能特性

### 🌐 多 BV 视频实时监控

* 支持并行监控多个 BV 号
* 每个 BV 拥有独立的监控线程与界面 Tab
* 自动获取封面并保存到 `<BV>/cover.jpg`
* 自动采样播放数、点赞、投币、评论、收藏、分享、弹幕等指标

### 📊 完整图表系统（4 图）

基于 Tkinter + Matplotlib：

* 播放增量曲线
* 点赞曲线
* 投币曲线
* 弹幕曲线
* 全部支持**滑动窗口流式更新（默认 20 点）**、自动缩放

### ⏱ 灵活的监控间隔

* 全局间隔（默认 75 秒）
* 每个 BV 可单独设置本地采样间隔
* 支持实时应用，无需重启

### 🚀 自动冲刺模式（距离目标 ≤ 500 播放）

自动触发：

1. 将采样间隔降为 **10 秒**
2. 发送一次**冲刺提醒**（合并转发）
3. 仅触发一次

### 🏆 里程碑推送

自动检测：

* 视频突破 **100 万**
* 如果已 >100 万，再突破 **1000 万**

触发一次合并转发推送。

### ➕ 手动推送 / 全部推送

支持：

* 单个 BV 的合并转发推送
* 所有 BV 的合并推送（列表式）
* 自动附带封面 base64 图片

### 🔁 OneBot WebSocket 支持（NapCat）

* QQ 群推送
* QQ 私聊推送
* 多群/多用户 ID（逗号分隔）
* 动态重连、随时保存配置

### 💾 数据持久化

每个 BV 会生成文件夹：

```
<BV>/
  ├── cover.jpg
  ├── <BV>.json
  └── <BV>.xlsx
```

---

## 📦 安装

### 环境

Python **3.8**

### 依赖安装

```bash
pip install bilibili-api-python pillow requests websockets matplotlib pandas openpyxl scikit-learn
```

---

## 🚀 运行

```bash
python gui.py
```

GUI 启动后将自动加载/生成配置文件 `bili_monitor_config.json`。

---

## 📁 目录结构

```
project/
│── gui.py                     # 主 GUI 界面
│── monitor/
│     ├── single_monitor.py    # 单个 BV 监控逻辑核心
│     ├── chart_widget.py      # 图表控件
│     ├── cover_widget.py      # 封面加载/展示
│     └── notifier.py          # OneBot WS 客户端
│── bili_monitor_config.json   # 程序配置（自动生成）
│── <BV>/
      ├── cover.jpg
      ├── <BV>.json
      └── <BV>.xlsx
```

---

## 📡 OneBot 推送说明

所有推送均使用 **合并转发消息**（NapCat 兼容）。
支持发送至：

* QQ 群
* QQ 私聊

包含数据：播放、点赞、投币、评论、收藏、分享、弹幕、增量、平均增量、预计达成时间、预计日期、封面图片。

---

## 📈 估算逻辑

计算：

* 平均增量
* 有效采样
* 达成目标的预计耗时
* 达成日期

数据同时写入 JSON 与 Excel，保证一致性与可导出性。

---

## 📝 License — MIT License

```
MIT License

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

---

