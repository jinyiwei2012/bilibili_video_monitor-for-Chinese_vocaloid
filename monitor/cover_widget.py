import threading
from io import BytesIO
import requests
from PIL import Image, ImageTk
import tkinter as tk

class CoverWidget:
    def __init__(self, parent_frame, on_log=None):
        self.parent_frame = parent_frame
        self.on_log = on_log or (lambda m: print(m))
        self._cover_photo = None
        self._cover_image_pil = None

        self.cover_label = tk.Label(parent_frame, text="封面加载中...", anchor="center")
        self.cover_label.pack(fill=tk.BOTH, expand=False)
        self.cover_label.bind("<Button-1>", lambda e: self.open_cover_big())

    def _log(self, msg):
        try:
            self.on_log(msg)
        except Exception:
            print(msg)

    def load_from_url(self, url, thumb_w=240):
        def _worker():
            try:
                r = requests.get(url, timeout=10)
                r.raise_for_status()
                img = Image.open(BytesIO(r.content)).convert("RGB")
                self._cover_image_pil = img.copy()
                w, h = img.size
                ratio = thumb_w / w
                new_h = int(h * ratio)
                thumb = img.resize((thumb_w, new_h), Image.LANCZOS)
                photo = ImageTk.PhotoImage(thumb)
                def set_img():
                    try:
                        self._cover_photo = photo
                        self.cover_label.config(image=photo, text="")
                    except Exception:
                        pass
                self.parent_frame.after(0, set_img)
            except Exception as e:
                self._log(f"加载封面失败: {e}")
                self.parent_frame.after(0, lambda: self.cover_label.config(text="封面加载失败"))
        threading.Thread(target=_worker, daemon=True).start()

    def open_cover_big(self):
        if not self._cover_image_pil:
            try:
                tk.messagebox.showinfo("提示", "封面尚未加载")
            except Exception:
                pass
            return
        big = tk.Toplevel(self.parent_frame)
        big.title("封面")
        img = self._cover_image_pil
        sw, sh = big.winfo_screenwidth(), big.winfo_screenheight()
        max_w, max_h = int(sw * 0.8), int(sh * 0.8)
        w, h = img.size
        scale = min(max_w / w, max_h / h, 1.0)
        new_w, new_h = int(w * scale), int(h * scale)
        display_img = img.resize((new_w, new_h), Image.LANCZOS)
        photo = ImageTk.PhotoImage(display_img)
        lbl = tk.Label(big, image=photo)
        lbl.image = photo
        lbl.pack(fill=tk.BOTH, expand=True)
