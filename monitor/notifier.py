# monitor/notifier.py
import asyncio
import threading
import traceback
import json
import websockets
import time

class OneBotWSClient:
    """
    OneBot WebSocket client with basic send queue and forward-message support for NapCat.
    get_config_callable() -> dict   (should include onebot_enabled, onebot_ws_url, onebot_bot_qq, onebot_group_ids, onebot_user_ids)
    on_log -> callable for logging
    """
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
            self.on_log("[OneBotWS] " + str(msg))
        except Exception:
            print("[OneBotWS]", msg)

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        self.log("started")

    def stop(self):
        self._stop_event.set()
        if self._loop:
            try:
                asyncio.run_coroutine_threadsafe(self._shutdown(), self._loop)
            except Exception:
                pass
        self.log("stopping")

    def send_msg(self, action, params):
        """
        Generic enqueue of a OneBot action (e.g. send_group_msg).
        Returns True if enqueued, False otherwise.
        """
        if not self._loop or not self._thread or not self._thread.is_alive():
            self.log("ws not running, starting")
            self.start()
            # slight delay to let loop come up
            time.sleep(0.1)
        if self._loop and self._send_queue:
            try:
                asyncio.run_coroutine_threadsafe(self._send_queue.put((action, params)), self._loop)
                self.log("enqueued %s %s" % (action, str(params)[:200]))
                return True
            except Exception as e:
                self.log("enqueue failed: %s" % e)
                return False
        else:
            self.log("loop/queue not ready")
            return False

    # convenience wrappers to send forward messages (NapCat)
    def send_group_forward(self, group_id, nodes):
        """
        nodes: list of forward nodes: each node is dict: {"type":"node", "data": {"name":..., "uin":..., "content": [...]} }
        NapCat expects key "messages" for send_group_forward_msg
        """
        params = {"group_id": int(group_id), "messages": nodes}
        return self.send_msg("send_group_forward_msg", params)

    def send_private_forward(self, user_id, nodes):
        params = {"user_id": int(user_id), "messages": nodes}
        return self.send_msg("send_private_forward_msg", params)

    # ----------------------------------------------------------------
    def _run_loop(self):
        try:
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            self._send_queue = asyncio.Queue()
            self._loop.run_until_complete(self._main())
        except Exception as e:
            self.log("ws loop error: %s\n%s" % (e, traceback.format_exc()))
        finally:
            try:
                if self._loop and not self._loop.is_closed():
                    self._loop.run_until_complete(self._loop.shutdown_asyncgens())
            except Exception:
                pass
            try:
                if self._loop and not self._loop.is_closed():
                    self._loop.close()
            except Exception:
                pass
            self._loop = None
            self.log("ws loop exited")

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
                self.log("connect %s" % ws_url)
                async with websockets.connect(ws_url) as ws:
                    self._ws = ws
                    self.log("connected")
                    reconnect_delay = 1
                    send_task = asyncio.create_task(self._send_loop(ws))
                    recv_task = asyncio.create_task(self._recv_loop(ws))
                    done, pending = await asyncio.wait([send_task, recv_task],
                                                       return_when=asyncio.FIRST_EXCEPTION)
                    for t in pending:
                        t.cancel()
            except Exception as e:
                self.log("ws error: %s" % e)
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(60, reconnect_delay * 2)
            finally:
                self._ws = None
        self.log("ws main exit")

    async def _send_loop(self, ws):
        while not self._stop_event.is_set():
            try:
                action, params = await self._send_queue.get()
                payload = {"action": action, "params": params}
                try:
                    await ws.send(json.dumps(payload, ensure_ascii=False))
                    self.log("sent: %s %s" % (action, str(params)[:200]))
                except Exception as e:
                    self.log("send error: %s" % e)
                    # if send fails, try to requeue with small delay
                    await asyncio.sleep(1)
                    try:
                        await self._send_queue.put((action, params))
                    except Exception:
                        pass
            except Exception as e:
                self.log("send loop exception: %s" % e)
                await asyncio.sleep(1)

    async def _recv_loop(self, ws):
        while not self._stop_event.is_set():
            try:
                msg = await ws.recv()
                self.log("recv: %s" % str(msg)[:400])
            except Exception as e:
                self.log("recv error: %s" % e)
                break
