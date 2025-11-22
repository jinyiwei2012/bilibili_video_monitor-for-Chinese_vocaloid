import os
import json
import datetime
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext

from monitor import SingleMonitor, OneBotWSClient

CONFIG_FILE = "bili_monitor_config.json"


def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


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

        # OneBot settings (supports multiple group/user IDs comma-separated)
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
        # read both legacy and new keys
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

        ttk.Button(onebot_frame, text="保存 OneBot 配置并(重)连", command=self.save_onebot_config).grid(row=0, column=3, padx=(8, 4))

        # BV list
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

        log_frame = ttk.LabelFrame(main, text="日志", padding=8)
        log_frame.pack(fill=tk.BOTH, pady=(0, 6), expand=False)
        self.log_text = scrolledtext.ScrolledText(log_frame, height=10)
        self.log_text.pack(fill=tk.BOTH, expand=True)

        # BV tabs
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
        self._log(f"已添加 {bv}")

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
            self._log(f"已移除 {bv}")

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
        self._log(f"已将间隔设置为 {v} 秒（实时生效）")
        # update effective interval for monitors that don't have local overrides
        for m in self.monitors.values():
            try:
                # only update those with empty local setting
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
            self._log(f"已保存默认间隔 {v} 秒")
        except Exception:
            messagebox.showerror("错误", "请输入有效正整数")

    def save_onebot_config(self):
        url = self.onebot_url_entry.get().strip()
        enabled = bool(self.onebot_enabled_var.get())
        gid_raw = self.onebot_group_entry.get().strip()
        uid_raw = self.onebot_user_entry.get().strip()

        # normalize to list or None
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
        # store lists (backwards-compatible logic kept)
        if group_ids is not None:
            self.config["onebot_group_ids"] = group_ids
        else:
            self.config.pop("onebot_group_ids", None)

        if user_ids is not None:
            self.config["onebot_user_ids"] = user_ids
        else:
            self.config.pop("onebot_user_ids", None)

        # also keep single legacy keys for backward compatibility (first element)
        if group_ids:
            self.config["onebot_group_id"] = group_ids[0]
        else:
            self.config.pop("onebot_group_id", None)

        if user_ids:
            self.config["onebot_user_id"] = user_ids[0]
        else:
            self.config.pop("onebot_user_id", None)

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

    # logging
    def _log(self, msg):
        ts = datetime.datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")
        try:
            self.log_text.insert(tk.END, f"{ts} {msg}\n")
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
