import asyncio
import threading
import traceback
import json
import websockets

class OneBotWSClient:
    def __init__(self, get_config_callable, on_log=None):
        self.get_config = get_config_callable
        self.on_log = on_log or (lambda m: print("[OneBotWS]", m))
        self._thread = None
        self._loop = None
        self._stop_event = threading.Event()
        self._send_queue = None
        self._ws = None

    def log(self, msg):
        try:
            self.on_log(f"[OneBotWS] {msg}")
        except Exception:
            print("[OneBotWS]", msg)

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        self.log("OneBot WS client started")

    def stop(self):
        self._stop_event.set()
        if self._loop:
            try:
                asyncio.run_coroutine_threadsafe(self._shutdown(), self._loop)
            except Exception:
                pass
        self.log("OneBot WS client stopping")

    def send_msg(self, action, params):

        if not self._loop or not self._thread or not self._thread.is_alive():
            self.log("WS client not running, starting")
            self.start()
        if self._loop and self._send_queue:
            try:
                asyncio.run_coroutine_threadsafe(self._send_queue.put((action, params)), self._loop)
                self.log(f"enqueue {action} {params}")
                return True
            except Exception as e:
                self.log(f"enqueue failed: {e}")
                return False
        else:
            self.log("WebSocket loop not ready")
            return False

    def _run_loop(self):
        try:
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            self._send_queue = asyncio.Queue()
            self._loop.run_until_complete(self._main())
        except Exception as e:
            self.log(f"WS loop error: {e}\n{traceback.format_exc()}")
        finally:
            try:
                if self._loop and not self._loop.is_closed():
                    self._loop.run_until_complete(self._loop.shutdown_asyncgens())
            except Exception:
                pass
            if self._loop and not self._loop.is_closed():
                try:
                    self._loop.close()
                except Exception:
                    pass
            self._loop = None
            self.log("WS loop exited")

    async def _shutdown(self):
        self._stop_event.set()
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass

    async def _main(self):
        reconnect_delay = 1
        while not self._stop_event.is_set():
            cfg = self.get_config() or {}
            ws_url = cfg.get("onebot_ws_url")
            enabled = cfg.get("onebot_enabled", False)
            if not enabled or not ws_url:
                await asyncio.sleep(1)
                continue
            try:
                self.log(f"connect {ws_url}")
                async with websockets.connect(ws_url) as ws:
                    self._ws = ws
                    self.log("WebSocket connected")
                    reconnect_delay = 1
                    send_task = asyncio.create_task(self._send_loop(ws))
                    recv_task = asyncio.create_task(self._recv_loop(ws))
                    done, pending = await asyncio.wait([send_task, recv_task],
                                                       return_when=asyncio.FIRST_EXCEPTION)
                    for t in pending:
                        t.cancel()
            except Exception as e:
                self.log(f"WS error: {e}")
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(60, reconnect_delay * 2)
            finally:
                self._ws = None
        self.log("WS main exit")

    async def _send_loop(self, ws):
        while not self._stop_event.is_set():
            try:
                action, params = await self._send_queue.get()
                payload = {"action": action, "params": params}
                # ensure JSON is serializable and maintain unicode
                await ws.send(json.dumps(payload, ensure_ascii=False))
                self.log(f"sent {payload}")
            except Exception as e:
                self.log(f"send failed: {e}")
                await asyncio.sleep(1)

    async def _recv_loop(self, ws):
        while not self._stop_event.is_set():
            try:
                msg = await ws.recv()
                self.log(f"recv: {msg}")
            except Exception as e:
                self.log(f"recv err: {e}")
                break
