# monitor/single_monitor.py
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

from .chart_widget import ChartWidget
from .cover_widget import CoverWidget

class SingleMonitor:
    """
    Single BV monitor that:
      - autosaves cover to <BV>/cover.jpg on first fetch
      - supports per-monitor interval
      - supports manual push that includes cover image as forward node (NapCat)
    """
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

        left_col = ttk.Frame(self.frame, width=260)
        left_col.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 6))
        self.cover_widget = CoverWidget(left_col, on_log=self.on_log)
        ttk.Button(left_col, text="保存封面", command=self.save_cover).pack(fill=tk.X, pady=(6, 0))

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

            with self._lock:
                if self.last_view is None:
                    view_inc = 0
                else:
                    view_inc = view - self.last_view
                self.last_view = view

            target_view = 10_000_000 if self.check_10m_mode else 1_000_000
            est_str, est_date, sc, avg_inc = self.calculate_estimated_time(self.data, view, target_view)

            self.frame.after(0, self._update_ui, view_inc, est_date)

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

            # milestone detect
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
        # save current cover image from cover_widget if loaded
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
        if len(data) < 2:
            return "数据不足", "数据不足", 0, 0
        valid = []
        total_time = 0
        total_inc = 0
        min_int = max(1, self.get_interval() * 0.5)
        max_int = max(1, self.get_interval() * 2)
        for i in range(1, len(data)):
            try:
                td = (self.parse_time(data[i]["time"]) - self.parse_time(data[i - 1]["time"])) .total_seconds()
            except Exception:
                continue
            if min_int <= td <= max_int:
                valid.append({"time_span": td, "view_increment": data[i].get("view_increment", 0)})
                total_time += td
                total_inc += data[i].get("view_increment", 0)
        if not valid:
            return "有效数据不足", "有效数据不足", 0, 0
        avg_sec = total_inc / total_time if total_time > 0 else 0
        avg_interval = total_inc / len(valid) if valid else 0
        if avg_sec <= 0:
            return "增量非正", "增量非正", len(valid), avg_interval
        remaining = target_view - current_view
        if remaining <= 0:
            return "已达成", "已达成", len(valid), avg_interval
        est_seconds = remaining / avg_sec
        est_date = datetime.datetime.now() + datetime.timedelta(seconds=est_seconds)
        est_date_str = est_date.strftime("%Y-%m-%d %H:%M:%S")
        if est_seconds < 60:
            return "约%d秒" % (est_seconds), est_date_str, len(valid), avg_interval
        elif est_seconds < 3600:
            return "约%.1f分钟" % (est_seconds/60.0), est_date_str, len(valid), avg_interval
        elif est_seconds < 86400:
            return "约%.1f小时" % (est_seconds/3600.0), est_date_str, len(valid), avg_interval
        else:
            return "约%.1f天" % (est_seconds/86400.0), est_date_str, len(valid), avg_interval

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

            # 构造文本（保持全部换行在单个 text 段中）
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

            # build forward node for this BV: use single text segment that contains \n
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
            text = "视频 %s 已达到里程碑: %s / %s" % (self.bv, view, target)

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
            self.log("里程碑通知已发")
        except Exception as e:
            self.log("里程碑通知失败: %s" % e)

    def _is_visible(self):
        """
        检查当前监控器界面是否可见（所在的 tab 是否是当前选中的）
        """
        try:
            # 如果 frame 被销毁，不可见
            if not self.frame.winfo_exists():
                return False

            # 找到该 frame 的 root notebook
            parent = self.frame.nametowidget(self.frame.winfo_parent())
            # 往上找 notebook
            while parent is not None:
                if isinstance(parent, ttk.Notebook):
                    # 当前选中的 tab
                    current = parent.select()
                    return str(self.frame) == str(current)
                parent = parent.nametowidget(parent.winfo_parent())
        except Exception:
            pass
        return True
