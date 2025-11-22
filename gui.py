# gui.py
import os
import json
import datetime
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext

from monitor import SingleMonitor, OneBotWSClient

CONFIG_FILE = "bili_monitor_config.json"
DEFAULT_BOT_QQ = 3807093079  # 由你提供

def load_config():
    cfg = {}
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            cfg = {}
    # ensure bot qq exists
    if "onebot_bot_qq" not in cfg or not cfg.get("onebot_bot_qq"):
        cfg["onebot_bot_qq"] = DEFAULT_BOT_QQ
    return cfg

def save_config(cfg):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=4)
    except Exception as e:
        print("保存配置失败:", e)

class BiliVideoMonitorGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("B站监控")
        self.root.geometry("1280x900")

        self.config = load_config()
        self.default_interval = int(self.config.get("default_interval", 75))

        self.obot_client = OneBotWSClient(lambda: self.config, on_log=self._log)
        if self.config.get("onebot_enabled", False) and self.config.get("onebot_ws_url"):
            self.obot_client.start()

        self.monitors = {}

        self._build_ui()

    def _build_ui(self):
        main = ttk.Frame(self.root, padding=8)
        main.pack(fill=tk.BOTH, expand=True)

        top = ttk.LabelFrame(main, text="设置", padding=8)
        top.pack(fill=tk.X, pady=(0, 6))

        ttk.Label(top, text="BV号:").grid(row=0, column=0, sticky=tk.W)
        self.bv_entry = ttk.Entry(top, width=20)
        self.bv_entry.grid(row=0, column=1, sticky=tk.W, padx=(4, 8))
        ttk.Button(top, text="添加", command=self.add_bv).grid(row=0, column=2, padx=(0, 8))

        ttk.Label(top, text="间隔(秒):").grid(row=0, column=3, sticky=tk.W, padx=(8, 4))
        self.interval_entry = ttk.Entry(top, width=8)
        self.interval_entry.grid(row=0, column=4, sticky=tk.W)
        self.interval_entry.insert(0, str(self.default_interval))
        ttk.Button(top, text="应用间隔（立即生效）", command=self.apply_interval).grid(row=0, column=5, padx=(8, 4))
        ttk.Button(top, text="保存默认间隔", command=self.save_default_interval).grid(row=0, column=6, padx=(8, 4))

        # OneBot
        onebot_frame = ttk.LabelFrame(main, text="OneBot (WebSocket) 设置", padding=8)
        onebot_frame.pack(fill=tk.X, pady=(0, 6))

        ttk.Label(onebot_frame, text="WS URL:").grid(row=0, column=0, sticky=tk.W)
        self.onebot_url_entry = ttk.Entry(onebot_frame, width=50)
        self.onebot_url_entry.grid(row=0, column=1, sticky=tk.W, padx=(4, 8))
        self.onebot_url_entry.insert(0, self.config.get("onebot_ws_url", ""))

        self.onebot_enabled_var = tk.BooleanVar(value=self.config.get("onebot_enabled", False))
        ttk.Checkbutton(onebot_frame, text="启用 OneBot 通知", variable=self.onebot_enabled_var).grid(row=0, column=2, padx=(8, 4))

        ttk.Label(onebot_frame, text="群 ID (可逗号分隔、多群):").grid(row=1, column=0, sticky=tk.W)
        self.onebot_group_entry = ttk.Entry(onebot_frame, width=30)
        self.onebot_group_entry.grid(row=1, column=1, sticky=tk.W, padx=(4, 8))
        groups_val = self.config.get("onebot_group_ids") or self.config.get("onebot_group_id", "")
        if isinstance(groups_val, (list, tuple)):
            groups_val = ",".join(str(x) for x in groups_val)
        self.onebot_group_entry.insert(0, str(groups_val))

        ttk.Label(onebot_frame, text="私聊用户 ID (可逗号分隔):").grid(row=1, column=2, sticky=tk.W)
        self.onebot_user_entry = ttk.Entry(onebot_frame, width=20)
        self.onebot_user_entry.grid(row=1, column=3, sticky=tk.W)
        users_val = self.config.get("onebot_user_ids") or self.config.get("onebot_user_id", "")
        if isinstance(users_val, (list, tuple)):
            users_val = ",".join(str(x) for x in users_val)
        self.onebot_user_entry.insert(0, str(users_val))

        ttk.Label(onebot_frame, text="Bot QQ (用于合并转发 uin):").grid(row=2, column=0, sticky=tk.W)
        self.onebot_botqq_entry = ttk.Entry(onebot_frame, width=20)
        self.onebot_botqq_entry.grid(row=2, column=1, sticky=tk.W)
        self.onebot_botqq_entry.insert(0, str(self.config.get("onebot_bot_qq", "")))

        ttk.Button(onebot_frame, text="保存 OneBot 配置并(重)连", command=self.save_onebot_config).grid(row=0, column=3, padx=(8, 4))

        list_frame = ttk.Frame(main)
        list_frame.pack(fill=tk.X, pady=(0, 6))

        self.bv_listbox = tk.Listbox(list_frame, height=6, selectmode=tk.EXTENDED)
        self.bv_listbox.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 0))

        list_btns = ttk.Frame(list_frame)
        list_btns.pack(side=tk.LEFT, padx=(6, 6))

        ttk.Button(list_btns, text="开始选中", command=self.start_selected).pack(fill=tk.X, pady=(0, 6))
        ttk.Button(list_btns, text="停止选中", command=self.stop_selected).pack(fill=tk.X, pady=(0, 6))
        ttk.Button(list_btns, text="移除选中", command=self.remove_selected).pack(fill=tk.X, pady=(0, 6))
        ttk.Button(list_btns, text="开始全部", command=self.start_all).pack(fill=tk.X, pady=(0, 6))
        ttk.Button(list_btns, text="停止全部", command=self.stop_all).pack(fill=tk.X, pady=(0, 6))
        ttk.Button(list_btns, text="全部推送", command=self.push_all).pack(fill=tk.X, pady=(0, 6))

        log_frame = ttk.LabelFrame(main, text="日志", padding=8)
        log_frame.pack(fill=tk.BOTH, pady=(0, 6), expand=False)
        self.log_text = scrolledtext.ScrolledText(log_frame, height=10)
        self.log_text.pack(fill=tk.BOTH, expand=True)

        self.bv_notebook = ttk.Notebook(main)
        self.bv_notebook.pack(fill=tk.BOTH, expand=True)

    # BV management
    def add_bv(self):
        bv = self.bv_entry.get().strip()
        if not bv:
            messagebox.showerror("错误", "请输入 BV 号")
            return
        if bv in self.monitors:
            messagebox.showwarning("提示", "该 BV 已添加")
            return
        self.bv_listbox.insert(tk.END, bv)

        tab = ttk.Frame(self.bv_notebook)
        self.bv_notebook.add(tab, text=bv)

        monitor = SingleMonitor(tab, bv, self.get_interval, self._log, obot_client=self.obot_client)
        self.monitors[bv] = monitor
        self._log("已添加 %s" % bv)

    def remove_selected(self):
        sel = self.bv_listbox.curselection()
        if not sel:
            messagebox.showwarning("提示", "请先选中")
            return
        for idx in reversed(sel):
            bv = self.bv_listbox.get(idx)
            if bv in self.monitors:
                try:
                    self.monitors[bv].stop()
                    self.monitors[bv].frame.destroy()
                except Exception:
                    pass
                del self.monitors[bv]
            self.bv_listbox.delete(idx)
            self._log("已移除 %s" % bv)

    def start_selected(self):
        sel = self.bv_listbox.curselection()
        if not sel:
            messagebox.showwarning("提示", "请选择要开始的 BV")
            return
        for idx in sel:
            bv = self.bv_listbox.get(idx)
            if bv in self.monitors:
                self.monitors[bv].start()

    def stop_selected(self):
        sel = self.bv_listbox.curselection()
        if not sel:
            messagebox.showwarning("提示", "请选择要停止的 BV")
            return
        for idx in sel:
            bv = self.bv_listbox.get(idx)
            if bv in self.monitors:
                self.monitors[bv].stop()

    def start_all(self):
        for m in self.monitors.values():
            m.start()

    def stop_all(self):
        for m in self.monitors.values():
            m.stop()

    # interval
    def get_interval(self):
        try:
            v = int(self.interval_entry.get().strip())
            if v <= 0:
                return max(1, self.default_interval)
            return v
        except Exception:
            return self.default_interval

    def apply_interval(self):
        v = self.get_interval()
        self.default_interval = v
        self.config["default_interval"] = v
        save_config(self.config)
        self._log("已将间隔设置为 %d 秒（实时生效）" % v)
        for m in self.monitors.values():
            try:
                if not m.interval_var.get().strip():
                    m.effective_interval_var.set(v)
            except Exception:
                pass

    def save_default_interval(self):
        try:
            v = int(self.interval_entry.get().strip())
            if v <= 0:
                raise ValueError
            self.default_interval = v
            self.config["default_interval"] = v
            save_config(self.config)
            self._log("已保存默认间隔 %d 秒" % v)
        except Exception:
            messagebox.showerror("错误", "请输入有效正整数")

    def save_onebot_config(self):
        url = self.onebot_url_entry.get().strip()
        enabled = bool(self.onebot_enabled_var.get())
        gid_raw = self.onebot_group_entry.get().strip()
        uid_raw = self.onebot_user_entry.get().strip()
        botqq_raw = self.onebot_botqq_entry.get().strip()

        def parse_ids(s):
            if s is None:
                return None
            s = str(s).strip()
            if not s:
                return None
            parts = [p.strip() for p in s.split(",") if p.strip()]
            out = []
            for p in parts:
                try:
                    out.append(int(p))
                except Exception:
                    pass
            return out if out else None

        group_ids = parse_ids(gid_raw)
        user_ids = parse_ids(uid_raw)

        self.config["onebot_ws_url"] = url
        self.config["onebot_enabled"] = enabled
        if group_ids is not None:
            self.config["onebot_group_ids"] = group_ids
        else:
            self.config.pop("onebot_group_ids", None)

        if user_ids is not None:
            self.config["onebot_user_ids"] = user_ids
        else:
            self.config.pop("onebot_user_ids", None)

        if group_ids:
            self.config["onebot_group_id"] = group_ids[0]
        else:
            self.config.pop("onebot_group_id", None)

        if user_ids:
            self.config["onebot_user_id"] = user_ids[0]
        else:
            self.config.pop("onebot_user_id", None)

        # bot qq
        try:
            botqq_val = int(botqq_raw)
            self.config["onebot_bot_qq"] = botqq_val
        except Exception:
            # keep existing or default
            pass

        save_config(self.config)
        try:
            self.obot_client.stop()
        except Exception:
            pass
        self.obot_client = OneBotWSClient(lambda: self.config, on_log=self._log)
        for m in self.monitors.values():
            m.obot_client = self.obot_client
        if enabled and url:
            self.obot_client.start()
            self._log("OneBot 客户端已启动（WebSocket）")
        else:
            self._log("OneBot 未启用或 URL 为空（已保存配置）")

    # 全部推送（合并转发）：对所有 BV 构造 nodes 列表并发出 forward
    def push_all(self):
        if not self.monitors:
            messagebox.showinfo("提示", "当前没有监控项")
            return
        if not self.obot_client:
            messagebox.showwarning("未启用 OneBot", "未配置 OneBot 客户端")
            return
        cfg = self.config or {}
        if not cfg.get("onebot_enabled", False):
            messagebox.showwarning("OneBot 未启用", "请先在设置中启用 OneBot")
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
        if not group_ids and not user_ids:
            messagebox.showwarning("目标为空", "请配置目标群或私聊用户")
            return

        bot_qq = str(cfg.get("onebot_bot_qq") or 0)
        # build a list of forward nodes: each monitor becomes a node (text + image if available)
        nodes = []
        for bv, mon in self.monitors.items():
            # get last sample
            with mon._lock:
                if not mon.data:
                    continue
                last = mon.data[-1]
            view = last.get("view", 0)
            like = last.get("like", 0)
            coin = last.get("coin", 0)
            reply = last.get("reply", 0)
            share = last.get("share", 0)
            danmaku = last.get("danmaku", 0)
            view_inc = last.get("view_increment", 0)
            sampling_time = last.get("time", "")
            favorite = last.get("favorite", 0)
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
                "数据采样时间: %s"
            ) % (mon.latest_info.get("title") if isinstance(mon.latest_info, dict) else bv, bv, view, like, coin, reply, favorite, share, danmaku, view_inc, sampling_time)

            # use a single text segment containing newline characters
            content = [
                {"type": "text", "data": {"text": text}}
            ]

            cover_path = mon.get_cover_path()
            if cover_path and os.path.exists(cover_path):
                try:
                    with open(cover_path, "rb") as f:
                        b = f.read()
                    import base64
                    b64 = base64.b64encode(b).decode()
                    content.append({"type": "image", "data": {"file": "base64://" + b64}})
                except Exception as e:
                    self._log("读取封面失败 %s: %s" % (bv, e))
            node = {"type": "node", "data": {"name": "监控器", "uin": bot_qq, "content": content}}
            nodes.append(node)

        sent_any = False
        # send to groups
        for gid in group_ids:
            try:
                ok = self.obot_client.send_group_forward(int(gid), nodes)
                sent_any = sent_any or bool(ok)
            except Exception as e:
                self._log("发送 group forward 错误: %s" % e)
        for uid in user_ids:
            try:
                ok = self.obot_client.send_private_forward(int(uid), nodes)
                sent_any = sent_any or bool(ok)
            except Exception as e:
                self._log("发送 private forward 错误: %s" % e)

        if sent_any:
            messagebox.showinfo("全部推送", "已发出全部推送（合并转发）")
        else:
            messagebox.showerror("推送失败", "发送失败，请检查 OneBot 日志")

    # logging
    def _log(self, msg):
        ts = datetime.datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")
        try:
            self.log_text.insert(tk.END, "%s %s\n" % (ts, msg))
            self.log_text.see(tk.END)
            self.root.update_idletasks()
        except Exception:
            print(ts, msg)

    def shutdown(self):
        for m in list(self.monitors.values()):
            try:
                m.stop()
            except Exception:
                pass
        try:
            self.obot_client.stop()
        except Exception:
            pass

def main():
    root = tk.Tk()
    app = BiliVideoMonitorGUI(root)

    def on_close():
        if messagebox.askokcancel("退出", "确定退出？"):
            try:
                app.shutdown()
            except Exception:
                pass
            root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()

if __name__ == "__main__":
    main()
