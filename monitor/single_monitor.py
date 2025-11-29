import threading
import datetime
import json
import os
import traceback
from bilibili_api import video
import tkinter as tk
from tkinter import ttk, messagebox
import pandas as pd
import asyncio
import requests
import base64
import numpy as np
import datetime
from statistics import median
from sklearn.linear_model import RANSACRegressor, LinearRegression
from .chart_widget import ChartWidget
from .cover_widget import CoverWidget
import math
class SingleMonitor:
    def __init__(self, parent_frame, bv, get_global_interval, on_log, obot_client=None):
        self.parent_frame = parent_frame
        self.bv = bv
        self.get_global_interval = get_global_interval
        self.on_log = on_log
        self.obot_client = obot_client

        self.is_monitoring = False
        self.thread = None
        self._lock = threading.Lock()
        self.latest_info = {}
        self.data = []
        self.last_view = None
        self.first_fetch = True
        self.check_10m_mode = False
        self.special_push_done = False
        self._load_state()  # 距目标≤500播放特殊推送

        self.max_points = tk.IntVar(value=20)
        self.interval_var = tk.StringVar(value="")
        self.effective_interval_var = tk.IntVar(value=self.get_global_interval())

        self._btn_busy = False
        self._btn_lock = threading.Lock()

        self._build_ui(parent_frame)
        self._init_charts()

    def _build_ui(self, frame):
        self.frame = ttk.Frame(frame)
        self.frame.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

        # Left column: fixed estimate block on top, then a scrollable container that contains
        # monitoring details AND cover (so they scroll together)
        left_col = ttk.Frame(self.frame, width=260)
        left_col.pack(side=tk.LEFT, fill=tk.BOTH, padx=(0, 6), expand=False)

        # ---------- 预计信息 (固定，不随滚动) ----------
        est_block = ttk.LabelFrame(left_col, text="预计信息", padding=(6,6))
        est_block.pack(fill=tk.X, pady=(0, 8))

        self._est_time_var = tk.StringVar(value="未计算")
        self._est_date_var = tk.StringVar(value="未计算")
        self._est_count_var = tk.StringVar(value="0")

        ttk.Label(est_block, text="预计达到目标时间:").grid(row=0, column=0, sticky=tk.W)
        ttk.Label(est_block, textvariable=self._est_time_var).grid(row=0, column=1, sticky=tk.W, padx=(6,0))
        ttk.Label(est_block, text="预计达到目标日期:").grid(row=1, column=0, sticky=tk.W)
        ttk.Label(est_block, textvariable=self._est_date_var).grid(row=1, column=1, sticky=tk.W, padx=(6,0))
        ttk.Label(est_block, text="(基于N个有效采样点):").grid(row=2, column=0, sticky=tk.W)
        ttk.Label(est_block, textvariable=self._est_count_var).grid(row=2, column=1, sticky=tk.W, padx=(6,0))

        # ---------- 监控信息（滚动区），此区域包含详细数据和封面（两者一起滚动） ----------
        scroll_container = ttk.Frame(left_col)
        scroll_container.pack(fill=tk.BOTH, expand=True)

        summary_canvas = tk.Canvas(scroll_container, highlightthickness=0)
        summary_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        scrollbar = ttk.Scrollbar(scroll_container, orient="vertical", command=summary_canvas.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        summary_canvas.configure(yscrollcommand=scrollbar.set)

        # inner frame inside canvas
        self.summary_frame = ttk.Frame(summary_canvas)
        summary_window = summary_canvas.create_window((0, 0), window=self.summary_frame, anchor="nw")

        def _on_summary_configure(event):
            summary_canvas.configure(scrollregion=summary_canvas.bbox("all"))
        self.summary_frame.bind("<Configure>", _on_summary_configure)

        def _resize_canvas(event):
            try:
                summary_canvas.itemconfigure(summary_window, width=event.width)
            except Exception:
                pass
        summary_canvas.bind("<Configure>", _resize_canvas)

        # mousewheel support
        def _on_mousewheel(event):
            # cross-platform handling
            try:
                if event.num == 4:
                    summary_canvas.yview_scroll(-1, "units")
                elif event.num == 5:
                    summary_canvas.yview_scroll(1, "units")
                else:
                    # Windows and Mac provide event.delta
                    delta = int(event.delta)
                    # On Windows delta is multiple of 120
                    step = -1 * int(delta/120) if delta % 120 == 0 else -1 * int(delta/3)
                    summary_canvas.yview_scroll(step, "units")
            except Exception:
                pass

        # Bindings (support many environments)
        summary_canvas.bind_all("<MouseWheel>", _on_mousewheel)
        summary_canvas.bind_all("<Button-4>", _on_mousewheel)
        summary_canvas.bind_all("<Button-5>", _on_mousewheel)

        # Build summary layout (inside the scrollable frame)
        self._summary_vars = {}

        # Title (own row)
        ttk.Label(self.summary_frame, text="视频标题:", font=(None, 9, "bold")).grid(row=0, column=0, sticky=tk.W, pady=(4,2))
        self._summary_vars["视频标题"] = tk.StringVar(value="-")
        ttk.Label(self.summary_frame, textvariable=self._summary_vars["视频标题"], wraplength=220, justify=tk.LEFT).grid(row=0, column=1, columnspan=2, sticky=tk.W)

        # Data time (own row)
        ttk.Label(self.summary_frame, text="数据时间:").grid(row=1, column=0, sticky=tk.W)
        self._summary_vars["数据时间"] = tk.StringVar(value="-")
        ttk.Label(self.summary_frame, textvariable=self._summary_vars["数据时间"]).grid(row=1, column=1, columnspan=2, sticky=tk.W)

        # separator
        ttk.Separator(self.summary_frame, orient=tk.HORIZONTAL).grid(row=2, column=0, columnspan=3, sticky="ew", pady=(6,6))

        # left & right metrics
        left_labels = ["播放数", "点赞", "硬币", "评论"]
        right_labels = ["收藏", "分享", "弹幕", "播放量增量", "平均增量"]

        for i, key in enumerate(left_labels, start=3):
            ttk.Label(self.summary_frame, text=f"{key}:").grid(row=i, column=0, sticky=tk.W, padx=(0,4))
            var = tk.StringVar(value="-")
            ttk.Label(self.summary_frame, textvariable=var).grid(row=i, column=1, sticky=tk.W)
            self._summary_vars[key] = var

        right_block = ttk.Frame(self.summary_frame)
        right_block.grid(row=3, column=2, rowspan=len(right_labels)+1, padx=(12,0), sticky=tk.N)

        for j, key in enumerate(right_labels):
            ttk.Label(right_block, text=f"{key}:").grid(row=j, column=0, sticky=tk.W, padx=(0,4))
            var = tk.StringVar(value="-")
            ttk.Label(right_block, textvariable=var).grid(row=j, column=1, sticky=tk.W)
            self._summary_vars[key] = var

        # ---------- 封面（放在可滚动区域的底部，与上面的详细数据一起滚动） ----------
        cover_holder = ttk.Frame(self.summary_frame)
        cover_holder.grid(row=3 + max(len(left_labels), len(right_labels)) + 2, column=0, columnspan=3, sticky="ew", pady=(8,0))
        self.cover_widget = CoverWidget(cover_holder, on_log=self.on_log)
        ttk.Button(cover_holder, text="保存封面", command=self.save_cover).pack(fill=tk.X, pady=(6, 0))

        # Right column: controls + charts (unchanged)
        right_col = ttk.Frame(self.frame)
        right_col.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        info = ttk.Frame(right_col)
        info.pack(fill=tk.X)
        ttk.Label(info, text=f"BV: {self.bv}").grid(row=0, column=0, sticky=tk.W)
        ttk.Label(info, text="增量:").grid(row=0, column=1, sticky=tk.W, padx=(8, 0))
        self.inc_lbl = ttk.Label(info, text="0")
        self.inc_lbl.grid(row=0, column=2, sticky=tk.W, padx=(4, 12))
        ttk.Label(info, text="预计:").grid(row=0, column=3, sticky=tk.W)
        self.est_lbl = ttk.Label(info, text="未计算")
        self.est_lbl.grid(row=0, column=4, sticky=tk.W, padx=(4, 12))

        interval_row = ttk.Frame(right_col)
        interval_row.pack(fill=tk.X, pady=(6, 0))
        ttk.Label(interval_row, text="本监控间隔(秒，留空使用全局):").pack(side=tk.LEFT)
        self.interval_entry = ttk.Entry(interval_row, width=8, textvariable=self.interval_var)
        self.interval_entry.pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(interval_row, text="应用本地间隔", command=self.apply_local_interval).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Label(interval_row, text="当前生效间隔:").pack(side=tk.LEFT, padx=(12, 0))
        self.eff_lbl = ttk.Label(interval_row, textvariable=self.effective_interval_var)
        self.eff_lbl.pack(side=tk.LEFT, padx=(6, 0))

        sw_ctrl = ttk.Frame(right_col)
        sw_ctrl.pack(fill=tk.X, pady=(6, 0))
        ttk.Label(sw_ctrl, text="滑动窗口大小(点数):").pack(side=tk.LEFT)
        self.sw_entry = ttk.Entry(sw_ctrl, width=6, textvariable=self.max_points)
        self.sw_entry.pack(side=tk.LEFT, padx=(6, 0))

        btns = ttk.Frame(right_col)
        btns.pack(fill=tk.X, pady=(6, 0))
        self.start_btn = ttk.Button(btns, text="开始", command=self.start)
        self.start_btn.pack(side=tk.LEFT, padx=(0, 6))
        self.stop_btn = ttk.Button(btns, text="停止", command=self.stop, state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT)
        self.push_btn = ttk.Button(btns, text="手动推送", command=self.manual_push)
        self.push_btn.pack(side=tk.LEFT, padx=(6, 0))

        self.notebook = ttk.Notebook(right_col)
        self.notebook.pack(fill=tk.BOTH, expand=True, pady=(8, 0))

        self.tab_inc = ttk.Frame(self.notebook)
        self.tab_like = ttk.Frame(self.notebook)
        self.tab_coin = ttk.Frame(self.notebook)
        self.tab_danmaku = ttk.Frame(self.notebook)

        self.notebook.add(self.tab_inc, text="增量")
        self.notebook.add(self.tab_like, text="点赞")
        self.notebook.add(self.tab_coin, text="投币")
        self.notebook.add(self.tab_danmaku, text="弹幕")

    def _init_charts(self):
        self.chart_inc = ChartWidget(self.tab_inc, f"{self.bv} - 增量", "增量", self.max_points)
        self.chart_like = ChartWidget(self.tab_like, f"{self.bv} - 点赞", "点赞", self.max_points)
        self.chart_coin = ChartWidget(self.tab_coin, f"{self.bv} - 投币", "投币", self.max_points)
        self.chart_danmaku = ChartWidget(self.tab_danmaku, f"{self.bv} - 弹幕", "弹幕", self.max_points)

    # (rest of the methods remain unchanged)

    def apply_local_interval(self):
        with self._btn_lock:
            if self._btn_busy:
                return
            self._btn_busy = True
        try:
            s = self.interval_var.get().strip()
            if not s:
                self.effective_interval_var.set(self.get_global_interval())
                self._log_local("已清空本地间隔，使用全局间隔")
                return
            try:
                v = int(s)
                if v <= 0:
                    raise ValueError
                self.effective_interval_var.set(v)
                self._log_local("已设置本地间隔 %d 秒" % v)
            except Exception:
                messagebox.showerror("错误", "请输入有效正整数或留空以使用全局")
        finally:
            with self._btn_lock:
                self._btn_busy = False

    def get_interval(self):
        try:
            v = int(self.effective_interval_var.get())
            if v > 0:
                return v
        except Exception:
            pass
        return self.get_global_interval()

    # The rest of the class methods are identical to the original implementation; for brevity
    # they are omitted here in the canvas version but in your working file please keep them.

    def start(self):
        with self._btn_lock:
            if self._btn_busy:
                return
            self._btn_busy = True
        try:
            if self.is_monitoring:
                messagebox.showwarning("提示", "%s 已在运行" % self.bv)
                return
            self.is_monitoring = True
            self.start_btn.config(state=tk.DISABLED)
            self.stop_btn.config(state=tk.NORMAL)
            self.thread = threading.Thread(target=self._run_loop, daemon=True)
            self.thread.start()
            self.log("开始监控")
        finally:
            with self._btn_lock:
                self._btn_busy = False

    def stop(self):
        with self._btn_lock:
            if self._btn_busy:
                return
            self._btn_busy = True
        try:
            if not self.is_monitoring:
                return
            self.is_monitoring = False
            self.start_btn.config(state=tk.NORMAL)
            self.stop_btn.config(state=tk.DISABLED)
            self.log("已请求停止")
        finally:
            with self._btn_lock:
                self._btn_busy = False

    def _run_loop(self):
        loop = None
        try:
            import asyncio
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self._monitor())
        except Exception as e:
            self.log("监控异常: %s\n%s" % (e, traceback.format_exc()))
        finally:
            try:
                if loop:
                    loop.close()
            except Exception:
                pass
            try:
                self.frame.after(0, lambda: (self.start_btn.config(state=tk.NORMAL), self.stop_btn.config(state=tk.DISABLED)))
            except Exception:
                pass

    async def _monitor(self):
        folder = self.bv
        os.makedirs(folder, exist_ok=True)
        json_file = os.path.join(folder, "%s.json" % self.bv)
        xlsx_file = os.path.join(folder, "%s.xlsx" % self.bv)

        consistent, loaded, _ = self.check_data_consistency(json_file, xlsx_file)
        if loaded:
            with self._lock:
                self.data = loaded
            self.last_view = self.data[-1].get("view", None)
            self.first_fetch = False
            if self.last_view and self.last_view >= 1_000_000:
                self.check_10m_mode = True
            self.log("加载历史 %d 条，last_view=%s" % (len(self.data), str(self.last_view)))

        # initial fetch (get cover and save)
        try:
            vinfo = await video.Video(bvid=self.bv).get_info()
            pic_url = vinfo.get("pic") or vinfo.get("cover") or vinfo.get("thumbnail")
            if pic_url:
                # load into cover widget and save to file
                self.cover_widget.load_from_url(pic_url)
                # try to save the original image to <bv>/cover.jpg
                try:
                    r = requests.get(pic_url, timeout=10)
                    r.raise_for_status()
                    folder = self.bv
                    os.makedirs(folder, exist_ok=True)
                    cover_path = os.path.join(folder, "cover.jpg")
                    with open(cover_path, "wb") as f:
                        f.write(r.content)
                    self.log("封面已自动保存: %s" % cover_path)
                except Exception as e:
                    self.log("保存封面失败: %s" % str(e))
        except Exception as e:
            self.log("获取 info/cover 失败: %s" % str(e))

        v = video.Video(bvid=self.bv)
        while self.is_monitoring:
            try:
                info = await v.get_info()
                self.latest_info = info or {}
            except Exception as e:
                interval = self.get_interval()
                self.log("获取失败: %s，%s 秒后重试" % (str(e), interval))
                await asyncio.sleep(interval)
                continue

            stat = info.get("stat", info)
            view = stat.get("view", 0)
            coin = stat.get("coin", 0)
            like = stat.get("like", 0)
            reply = stat.get("reply", 0)
            share = stat.get("share", 0)
            danmaku = stat.get("danmaku", 0)
            tms = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            # sprint mode / special notify
            target_view = 10_000_000 if self.check_10m_mode else 1_000_000
            remaining = target_view - view

            if remaining <= 500 and remaining > 0:
                if self.get_interval() != 10:
                    self.effective_interval_var.set(10)
                    self.log("进入冲刺模式：距离目标 <=500 播放，间隔已临时降至 10 秒")
                if not self.special_push_done:
                    self.special_push_done = True
                    self._notify_special_remaining(remaining, view, target_view)
                    self._save_state()

            with self._lock:
                if self.last_view is None:
                    view_inc = 0
                else:
                    view_inc = view - self.last_view
                self.last_view = view

            est_str, est_date, sc, avg_inc = self.calculate_estimated_time(self.data, view, target_view)

            # UI update
            try:
                self.frame.after(0, self._update_ui, view_inc, est_date)
            except Exception:
                pass

            rec = {
                "time": tms,
                "view": view,
                "like": like,
                "coin": coin,
                "reply": reply,
                "share": share,
                "danmaku": danmaku,
                "favorite": stat.get("favorite", 0),
                "view_increment": view_inc,
                "avg_increment_per_interval": avg_inc,
                "estimated_time": est_str,
                "estimated_date": est_date,
                "sample_count": sc
            }

            with self._lock:
                self.data.append(rec)

            ok, msg = self.write_data(json_file, xlsx_file, self.data)
            if not ok:
                self.log("写入失败: %s" % msg)
                with self._lock:
                    self.data.pop()

            self.log("样本: view=%s inc=%s like=%s coin=%s danmaku=%s" % (view, view_inc, like, coin, danmaku))

            # milestone
            if self.first_fetch:
                self.first_fetch = False
                if view >= 1_000_000:
                    self.check_10m_mode = True
                    self.log("首次 >=100万，进入1000万模式")
                    self._notify_milestone(1_000_000, view)
            else:
                if self.check_10m_mode and view >= 10_000_000:
                    self.log("突破1000万")
                    self._notify_milestone(10_000_000, view)
                    self.frame.after(0, self.stop)
                    break
                elif not self.check_10m_mode and view >= 1_000_000:
                    self.log("突破100万")
                    self._notify_milestone(1_000_000, view)
                    self.frame.after(0, self.stop)
                    break

            self.frame.after(0, self._update_all_charts)
            await asyncio.sleep(self.get_interval())

        self.log("监控结束")

    def _update_ui(self, inc, est):
        try:
            self.inc_lbl.config(text=str(inc))
            self.est_lbl.config(text=est)

            with self._lock:
                last = self.data[-1] if self.data else None

            if last:
                title = ""
                try:
                    if isinstance(self.latest_info, dict):
                        title = self.latest_info.get("title") or self.latest_info.get("name") or ""
                except Exception:
                    title = ""
                if not title:
                    title = self.bv

                # title + data time
                self._summary_vars["视频标题"].set(title)
                self._summary_vars["数据时间"].set(last.get("time", "-"))

                # left metrics
                self._summary_vars["播放数"].set(str(last.get("view", 0)))
                self._summary_vars["点赞"].set(str(last.get("like", 0)))
                self._summary_vars["硬币"].set(str(last.get("coin", 0)))
                self._summary_vars["评论"].set(str(last.get("reply", 0)))

                # right metrics
                self._summary_vars["收藏"].set(str(last.get("favorite", 0)))
                self._summary_vars["分享"].set(str(last.get("share", 0)))
                self._summary_vars["弹幕"].set(str(last.get("danmaku", 0)))
                self._summary_vars["播放量增量"].set(str(last.get("view_increment", 0)))
                self._summary_vars["平均增量"].set(str(last.get("avg_increment_per_interval", 0)))

                # estimates
                self._est_time_var.set(last.get("estimated_time", "未计算"))
                self._est_date_var.set(last.get("estimated_date", "未计算"))
                self._est_count_var.set(str(last.get("sample_count", 0)))

        except Exception:
            pass

    def _update_all_charts(self):
        with self._lock:
            if not self.data:
                return
            N = max(1, int(self.max_points.get()))
            window = self.data[-N:]
            incs = [d.get("view_increment", 0) for d in window]
            likes = [d.get("like", 0) for d in window]
            coins = [d.get("coin", 0) for d in window]
            dans = [d.get("danmaku", 0) for d in window]

        if not self._is_visible():
            return

        self.chart_inc.update(incs)
        self.chart_like.update(likes)
        self.chart_coin.update(coins)
        self.chart_danmaku.update(dans)

    def save_cover(self):
        if not getattr(self.cover_widget, "_cover_image_pil", None):
            messagebox.showinfo("提示", "封面尚未加载")
            return
        folder = self.bv
        os.makedirs(folder, exist_ok=True)
        fname = os.path.join(folder, "cover.jpg")
        try:
            self.cover_widget._cover_image_pil.save(fname, format="JPEG")
            messagebox.showinfo("保存成功", "已保存: %s" % fname)
            self.log("封面已保存: %s" % fname)
        except Exception as e:
            messagebox.showerror("保存失败", str(e))
            self.log("保存封面失败: %s" % e)

    def get_cover_path(self):
        p = os.path.join(self.bv, "cover.jpg")
        if os.path.exists(p):
            return p
        return None

    def check_data_consistency(self, json_file, xlsx_file):
        json_exists = os.path.exists(json_file)
        xlsx_exists = os.path.exists(xlsx_file)
        if not json_exists and not xlsx_exists:
            return True, [], "无历史"
        if json_exists and not xlsx_exists:
            try:
                with open(json_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return False, data, "仅 JSON"
            except Exception as e:
                return False, [], "JSON 读错: %s" % e
        if not json_exists and xlsx_exists:
            try:
                df = pd.read_excel(xlsx_file)
                return False, df.to_dict("records"), "仅 XLSX"
            except Exception as e:
                return False, [], "XLSX 读错: %s" % e
        try:
            with open(json_file, "r", encoding="utf-8") as f:
                jdata = json.load(f)
            df = pd.read_excel(xlsx_file)
            xdata = df.to_dict("records")
            if len(jdata) != len(xdata):
                return False, jdata, "长度不一致"
            for i, (ja, xa) in enumerate(zip(jdata, xdata)):
                if ja.get("view") != xa.get("view") or ja.get("time") != xa.get("time"):
                    return False, jdata, "第%d条不一致" % (i+1)
            return True, jdata, "一致"
        except Exception as e:
            return False, jdata if 'jdata' in locals() else [], "检查失败: %s" % e

    def write_data(self, json_file, xlsx_file, data):
        try:
            with open(json_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
            pd.DataFrame(data).to_excel(xlsx_file, index=False)
            return True, "ok"
        except Exception as e:
            if os.path.exists(json_file):
                return True, "JSON ok but XLSX failed: %s" % e
            else:
                return False, "写入失败: %s" % e

    def log(self, msg):
        try:
            self.on_log("[%s] %s" % (self.bv, msg))
        except Exception:
            print("[%s] %s" % (self.bv, msg))

    def _log_local(self, msg):
        try:
            self.on_log("[%s][local] %s" % (self.bv, msg))
        except Exception:
            print("[%s][local] %s" % (self.bv, msg))

    def parse_time(self, tstr):
        return datetime.datetime.strptime(tstr, "%Y-%m-%d %H:%M:%S")

    def calculate_estimated_time(self, data, current_view, target_view):
        """
        增强版预测模型：
        1. RANSAC 回归（主模型）
        2. 分段线性回归（自动寻找最佳分段点）
        3. 指数衰减增量预测（对未来增量趋势进行校正）
        4. 动态权重融合
        5. 基于局部“斜率”而非增量(diff)的异常过滤
        """

        # ------------------------------
        # 0. 数据准备
        # ------------------------------
        if len(data) < 6:
            return "数据不足", "数据不足", len(data), 0

        xs, ys = [], []

        try:
            t0 = self.parse_time(data[0]["time"])
        except:
            return "时间格式错误", "时间格式错误", 0, 0

        for rec in data:
            try:
                t = (self.parse_time(rec["time"]) - t0).total_seconds()
                v = rec.get("view", 0)
                if t >= 0 and v >= 0:
                    xs.append(t)
                    ys.append(v)
            except:
                pass

        xs = np.array(xs, dtype=float)
        ys = np.array(ys, dtype=float)

        if len(xs) < 6:
            return "有效数据不足", "有效数据不足", len(xs), 0

        # ------------------------------
        # 1. 异常过滤（基于局部斜率 slope）
        # ------------------------------
        slopes = np.diff(ys) / np.diff(xs)
        if len(slopes) >= 5:
            med = median(slopes)
            mad = median(abs(slopes - med)) or 1
            threshold = mad * 6

            mask = [True]
            for sl in slopes:
                mask.append(abs(sl - med) <= threshold)

            xs = xs[mask]
            ys = ys[mask]

            if len(xs) < 6:
                return "有效数据不足", "有效数据不足", len(xs), med

        # ------------------------------
        # 2. RANSAC（主模型）
        # ------------------------------
        try:
            base = LinearRegression(fit_intercept=True)
            ransac = RANSACRegressor(
                base,
                min_samples=max(4, len(xs) // 5),
                residual_threshold=np.std(ys) * 0.8,
                max_trials=100
            )
            ransac.fit(xs.reshape(-1, 1), ys)

            a_r = ransac.estimator_.coef_[0]
            b_r = ransac.estimator_.intercept_
        except:
            return "RANSAC失败", "RANSAC失败", len(xs), 0

        if a_r <= 0:
            return "增量非正", "增量非正", len(xs), 0

        # ------------------------------
        # 3. 分段线性回归（自动寻找最佳分段点）
        # ------------------------------
        def segment_fit(xs, ys, k):
            """
            给定分段点 k，拟合两段直线，返回总误差（SSE）
            """
            try:
                # 第一段
                A1 = np.vstack([xs[:k], np.ones(k)]).T
                p1 = np.linalg.lstsq(A1, ys[:k], rcond=None)[0]

                # 第二段
                A2 = np.vstack([xs[k:], np.ones(len(xs) - k)]).T
                p2 = np.linalg.lstsq(A2, ys[k:], rcond=None)[0]

                # 计算误差
                pred1 = A1 @ p1
                pred2 = A2 @ p2
                sse = np.sum((ys[:k] - pred1) ** 2) + np.sum((ys[k:] - pred2) ** 2)

                return sse, p1, p2
            except:
                return 1e18, None, None

        best_sse = 1e18
        best_p1 = best_p2 = None

        # 分段点 k 至少在 20% ~ 80% 之间
        for k in range(int(len(xs) * 0.2), int(len(xs) * 0.8)):
            sse, p1, p2 = segment_fit(xs, ys, k)
            if sse < best_sse:
                best_sse = sse
                best_p1, best_p2 = p1, p2

        # 使用第二段斜率作为“局部趋势”
        if best_p2 is not None:
            a_seg = best_p2[0]
            b_seg = best_p2[1]
        else:
            a_seg = a_r
            b_seg = b_r

        if a_seg <= 0:
            a_seg = a_r

        # ------------------------------
        # 4. 指数衰减模型（预测未来增量下降趋势）
        # ------------------------------
        incs = np.diff(ys)
        if len(incs) > 5:
            # 最近 5 个增量的衰减速度
            recent = incs[-5:]
            ratios = []
            for i in range(1, len(recent)):
                if recent[i - 1] > 0:
                    ratios.append(recent[i] / recent[i - 1])

            decay = np.median(ratios) if ratios else 1.0
            decay = max(0.80, min(decay, 1.0))  # 限制在 0.80~1.0 比较稳健
        else:
            decay = 1.0

        # 当前增量估计
        current_inc = incs[-1] if len(incs) else 0
        if current_inc <= 0:
            current_inc = a_r  # fallback

        # 预估达成需要的时间（指数衰减积分）
        remain = target_view - current_view
        if remain <= 0:
            return "已达成", "已达成", len(xs), current_inc

        # 指数衰减求解：sum(current_inc * decay^t) >= remain
        try:
            if decay < 0.999:
                est_exp = math.log(1 - remain * (1 - decay) / current_inc) / math.log(decay)
                est_exp = max(est_exp, 0)
            else:
                est_exp = remain / current_inc
        except:
            est_exp = remain / max(current_inc, 1)

        # ------------------------------
        # 5. 三模型融合（动态权重）
        # ------------------------------

        # ① RANSAC 预测
        est_r = (target_view - current_view) / a_r

        # ② 分段线性预测
        est_s = (target_view - current_view) / a_seg

        # ③ 指数衰减预测
        est_e = est_exp

        # --- 动态权重 ---
        # 模型稳定性指标
        inlier_ratio = ransac.inlier_mask_.mean()
        slope_stab = 1 / (np.std(incs[-5:]) + 1e-6)

        # RANSAC权重随内点比例变化
        w_r = min(0.85, 0.4 + inlier_ratio)

        # 分段线性在“后期”趋势明显时更重
        w_s = min(0.4, slope_stab * 0.25)

        # 指数衰减主要防止后期过度乐观
        w_e = 1 - w_r - w_s
        w_e = max(0.05, w_e)

        # 融合
        est_seconds = w_r * est_r + w_s * est_s + w_e * est_e

        if est_seconds < 0:
            return "已达成", "已达成", len(xs), current_inc

        # ------------------------------
        # 6. 输出格式化
        # ------------------------------
        est_dt = datetime.datetime.now() + datetime.timedelta(seconds=est_seconds)
        est_date = est_dt.strftime("%Y-%m-%d %H:%M:%S")

        if est_seconds < 60:
            human = f"约{int(est_seconds)}秒"
        elif est_seconds < 3600:
            human = f"约{est_seconds / 60:.1f}分钟"
        elif est_seconds < 86400:
            human = f"约{est_seconds / 3600:.1f}小时"
        else:
            human = f"约{est_seconds / 86400:.1f}天"

        # 平均增量
        avg_inc = np.mean(incs[incs >= 0]) if len(incs) else 0

        return human, est_date, len(xs), avg_inc

    def manual_push(self):
        """
        Build forward nodes for this BV and send via OneBotWSClient.
        """
        with self._btn_lock:
            if self._btn_busy:
                return
            self._btn_busy = True
        try:
            with self._lock:
                if not self.data:
                    messagebox.showinfo("提示", "当前暂无样本数据，无法推送")
                    return
                last = self.data[-1]
                view = last.get("view", 0)
                like = last.get("like", 0)
                coin = last.get("coin", 0)
                reply = last.get("reply", 0)
                share = last.get("share", 0)
                danmaku = last.get("danmaku", 0)
                view_inc = last.get("view_increment", 0)
                sampling_time = last.get("time", "")
                favorite = last.get("favorite", 0)
                avg_inc = last.get("avg_increment_per_interval", 0)
                est_str = last.get("estimated_time", "未计算")
                est_date = last.get("estimated_date", "未计算")
                valid_count = last.get("sample_count", 0)

            target = 10_000_000 if self.check_10m_mode else 1_000_000
            est_str, est_date, valid_count, avg_inc = self.calculate_estimated_time(self.data, view, target)

            title = ""
            try:
                if isinstance(self.latest_info, dict):
                    title = self.latest_info.get("title") or self.latest_info.get("name") or ""
            except Exception:
                title = ""
            if not title:
                title = self.bv

            text = (
                "视频标题:%s\n"
                "视频bv号:%s\n"
                "播放数: %s\n"
                "点赞: %s\n"
                "硬币: %s\n"
                "评论: %s\n"
                "收藏: %s\n"
                "分享: %s\n"
                "弹幕: %s\n"
                "播放量增量: %s\n"
                "平均增量(每采样间隔): %s\n"
                "预计达到目标时间: %s\n"
                "预计达到目标日期: %s\n"
                "数据采样时间: %s\n"
                "(基于%d个有效采样点)"
            ) % (title, self.bv, view, like, coin, reply, favorite, share, danmaku, view_inc, avg_inc, est_str, est_date, sampling_time, valid_count)

            if not self.obot_client:
                messagebox.showwarning("未启用 OneBot", "未配置 OneBot 客户端，无法推送")
                return
            cfg = {}
            try:
                cfg = self.obot_client.get_config() or {}
            except Exception:
                cfg = {}

            enabled = cfg.get("onebot_enabled", False)
            if not enabled:
                messagebox.showwarning("OneBot 未启用", "请在设置中启用 OneBot 后再推送")
                return

            # gather targets
            group_ids = cfg.get("onebot_group_ids") or cfg.get("onebot_group_id") or []
            user_ids = cfg.get("onebot_user_ids") or cfg.get("onebot_user_id") or []

            def normalize_list(x):
                if x is None:
                    return []
                if isinstance(x, (list, tuple)):
                    return [int(i) for i in x if str(i).strip()]
                s = str(x).strip()
                if not s:
                    return []
                parts = [p.strip() for p in s.split(",") if p.strip()]
                out = []
                for p in parts:
                    try:
                        out.append(int(p))
                    except Exception:
                        continue
                return out

            group_ids = normalize_list(group_ids)
            user_ids = normalize_list(user_ids)

            bot_qq = str(cfg.get("onebot_bot_qq") or cfg.get("bot_qq") or 0)

            node_content = [
                {"type": "text", "data": {"text": text}}
            ]

            cover_path = self.get_cover_path()
            if cover_path and os.path.exists(cover_path):
                try:
                    with open(cover_path, "rb") as f:
                        b = f.read()
                    b64 = base64.b64encode(b).decode()
                    node_content.append({"type": "image", "data": {"file": "base64://" + b64}})
                except Exception as e:
                    self.log("读取封面失败: %s" % e)

            node = {"type": "node", "data": {"name": "监控器", "uin": bot_qq, "content": node_content}}

            sent_any = False
            for gid in group_ids:
                try:
                    ok = self.obot_client.send_group_forward(int(gid), [node])
                    sent_any = sent_any or bool(ok)
                except Exception as e:
                    self.log("发送 group forward 失败: %s" % e)
            for uid in user_ids:
                try:
                    ok = self.obot_client.send_private_forward(int(uid), [node])
                    sent_any = sent_any or bool(ok)
                except Exception as e:
                    self.log("发送 private forward 失败: %s" % e)

            if sent_any:
                self.log("手动推送已发送")
                messagebox.showinfo("推送成功", "手动推送已发送（请查看 OneBot 日志）")
            else:
                self.log("手动推送失败")
                messagebox.showerror("推送失败", "发送失败，请查看日志或检查 OneBot 连接")
        except Exception as e:
            self.log("手动推送异常: %s" % e)
            messagebox.showerror("错误", "手动推送失败: %s" % e)
        finally:
            with self._btn_lock:
                self._btn_busy = False

    def _notify_milestone(self, target, view):
        """
        里程碑推送：内容格式完全与手动推送一致
        唯一区别：预计达成 → 已达成
        """
        try:
            if not self.obot_client:
                return
            cfg = self.obot_client.get_config() or {}
            if not cfg.get("onebot_enabled", False):
                return

            # ---- 取推送目标 ----
            group_ids = cfg.get("onebot_group_ids") or cfg.get("onebot_group_id") or []
            user_ids = cfg.get("onebot_user_ids") or cfg.get("onebot_user_id") or []

            def normalize_list(x):
                if x is None:
                    return []
                if isinstance(x, (list, tuple)):
                    return [int(i) for i in x if str(i).strip()]
                s = str(x).strip()
                if not s:
                    return []
                parts = [p.strip() for p in s.split(",") if p.strip()]
                out = []
                for p in parts:
                    try:
                        out.append(int(p))
                    except:
                        continue
                return out

            group_ids = normalize_list(group_ids)
            user_ids = normalize_list(user_ids)
            bot_qq = str(cfg.get("onebot_bot_qq") or 0)

            # ---- 读取最新数据 ----
            with self._lock:
                last = self.data[-1] if self.data else None

            if not last:
                return

            title = ""
            try:
                title = (
                    self.latest_info.get("title")
                    if isinstance(self.latest_info, dict)
                    else self.bv
                )
            except:
                title = self.bv

            like = last.get("like", 0)
            coin = last.get("coin", 0)
            reply = last.get("reply", 0)
            share = last.get("share", 0)
            danmaku = last.get("danmaku", 0)
            favorite = last.get("favorite", 0)
            sampling_time = last.get("time", "-")
            view_inc = last.get("view_increment", 0)
            avg_inc = last.get("avg_increment_per_interval", 0)
            sample_count = last.get("sample_count", 0)

            now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            # ---- 里程碑推送文本（完全与手动一致，但“预计”→“已达成”）----
            text = (
                       "【里程碑已达成】\n"
                       "视频标题:%s\n"
                       "视频bv号:%s\n"
                       "播放数: %s\n"
                       "点赞: %s\n"
                       "硬币: %s\n"
                       "评论: %s\n"
                       "收藏: %s\n"
                       "分享: %s\n"
                       "弹幕: %s\n"
                       "播放量增量: %s\n"
                       "平均增量(每采样间隔): %s\n"
                       "已达成目标时间: %s\n"
                       "已达成目标日期: %s\n"
                       "数据采样时间: %s\n"
                       "(基于%d个有效采样点)"
                   ) % (
                       title, self.bv, view, like, coin, reply, favorite,
                       share, danmaku, view_inc, avg_inc,
                       now, now, sampling_time, sample_count
                   )

            node_content = [{"type": "text", "data": {"text": text}}]

            # ---- 封面 ----
            cover_path = self.get_cover_path()
            if cover_path and os.path.exists(cover_path):
                try:
                    with open(cover_path, "rb") as f:
                        b = f.read()
                    b64 = base64.b64encode(b).decode()
                    node_content.append(
                        {"type": "image", "data": {"file": "base64://" + b64}}
                    )
                except Exception as e:
                    self.log("封面读取失败: %s" % e)

            node = {
                "type": "node",
                "data": {"name": "监控器", "uin": bot_qq, "content": node_content},
            }

            # ---- 推送 ----
            for gid in group_ids:
                try:
                    self.obot_client.send_group_forward(int(gid), [node])
                except:
                    pass
            for uid in user_ids:
                try:
                    self.obot_client.send_private_forward(int(uid), [node])
                except:
                    pass

            self.log("里程碑推送已发送")

        except Exception as e:
            self.log("里程碑通知失败: %s" % e)

    def _save_state(self):
        try:
            folder = self.bv
            os.makedirs(folder, exist_ok=True)
            with open(os.path.join(folder, "state.json"), "w", encoding="utf-8") as f:
                json.dump({"special_push_done": self.special_push_done}, f)
        except:
            pass

    def _load_state(self):
        try:
            p = os.path.join(self.bv, "state.json")
            if os.path.exists(p):
                with open(p, "r", encoding="utf-8") as f:
                    d = json.load(f)
                self.special_push_done = d.get("special_push_done", False)
        except:
            pass

    def _notify_special_remaining(self, remaining, view, target):
        try:
            if not self.obot_client:
                return
            cfg = self.obot_client.get_config() or {}
            if not cfg.get("onebot_enabled", False):
                return

            group_ids = cfg.get("onebot_group_ids") or cfg.get("onebot_group_id") or []
            user_ids = cfg.get("onebot_user_ids") or cfg.get("onebot_user_id") or []

            def normalize_list(x):
                if x is None:
                    return []
                if isinstance(x, (list, tuple)):
                    return [int(i) for i in x if str(i).strip()]
                s = str(x).strip()
                if not s:
                    return []
                parts = [p.strip() for p in s.split(",") if p.strip()]
                out = []
                for p in parts:
                    try:
                        out.append(int(p))
                    except Exception:
                        continue
                return out

            group_ids = normalize_list(group_ids)
            user_ids = normalize_list(user_ids)

            bot_qq = str(cfg.get("onebot_bot_qq") or 0)

            text = (
                f"[冲刺提醒]\n"
                f"BV {self.bv}\n"
                f"当前播放: {view}\n"
                f"目标: {target}\n"
                f"距离目标还有 {remaining} 播放！\n"
                f"已自动切换到 10 秒采样间隔。"
            )

            node_content = [{"type": "text", "data": {"text": text}}]
            node = {"type": "node", "data": {"name": "监控器", "uin": bot_qq, "content": node_content}}

            for gid in group_ids:
                try:
                    self.obot_client.send_group_forward(int(gid), [node])
                except Exception:
                    pass

            for uid in user_ids:
                try:
                    self.obot_client.send_private_forward(int(uid), [node])
                except Exception:
                    pass

            self.log("已发送冲刺模式提醒推送")

        except Exception as e:
            self.log("冲刺推送失败: %s" % e)

    def _is_visible(self):
        try:
            if not self.frame.winfo_exists():
                return False

            p = self.frame
            outer_tab = None
            while True:
                parent = p.nametowidget(p.winfo_parent())
                if isinstance(parent, ttk.Notebook):
                    outer_tab = parent
                    break
                p = parent

            if outer_tab is None:
                return True

            current = outer_tab.select()
            my_tab = self.frame.master
            return str(my_tab) == str(current)

        except Exception:
            return True
