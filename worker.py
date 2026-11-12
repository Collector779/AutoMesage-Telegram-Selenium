"""Background thread that owns the Selenium driver. The GUI talks to it via queues."""
import queue
import shutil
import threading
import time
import traceback

import telegram_api
import telegram_login as login
from config import profile_dir
from telegram_browser import start_browser
from telegram_scheduler import Scheduler


class BrowserWorker(threading.Thread):
    def __init__(self, events: queue.Queue, settings: dict):
        super().__init__(daemon=True)
        self.events = events          # worker -> GUI: (kind, payload)
        self.commands = queue.Queue()  # GUI -> worker: (name, args)
        self.settings = settings
        self.driver = None
        self.scheduler = None
        self.stop_scan = threading.Event()
        self._last_snapshot = 0.0

    # ---- API used by the GUI thread -------------------------------------------------
    def send(self, name, *args):
        self.commands.put((name, args))

    # ---- helpers --------------------------------------------------------------------
    def emit(self, kind, payload=None):
        self.events.put((kind, payload))

    def log(self, text, replace=False):
        self.emit("log_replace" if replace else "log", text)

    def _set_busy(self, busy, text=""):
        self.emit("busy", (busy, text))

    def _report_state(self, state, error=""):
        self.emit("login_state", (state, error))

    # ---- main loop ------------------------------------------------------------------
    def run(self):
        while True:
            try:
                name, args = self.commands.get(timeout=1.0)
            except queue.Empty:
                self._scheduler_tick()
                continue
            if name == "shutdown":
                self._quit_driver()
                self.emit("closed")
                return
            handler = getattr(self, f"cmd_{name}", None)
            if handler is None:
                continue
            try:
                handler(*args)
            except Exception as err:
                self.log(f"Blad ({name}): {err}")
                self.log(traceback.format_exc(limit=3))
                self._set_busy(False)

    def _scheduler_tick(self):
        if not (self.scheduler and self.driver):
            return
        try:
            self.scheduler.tick(self.driver)
        except Exception as err:
            self.log(f"Blad harmonogramu: {err}")
        if time.time() - self._last_snapshot > 1.0:
            self._last_snapshot = time.time()
            self.emit("schedule", self.scheduler.snapshot())

    def _quit_driver(self):
        if self.driver is not None:
            try:
                self.driver.quit()
            except Exception:
                pass
            self.driver = None

    # ---- commands -------------------------------------------------------------------
    def cmd_start(self):
        self._quit_driver()
        headless = bool(self.settings.get("headless", True))
        self._set_busy(True, "Uruchamianie przegladarki...")
        self.log("Uruchamianie przegladarki" + (" w tle..." if headless else " (widoczne okno)..."))
        self.driver = start_browser(headless=headless)
        self.log("Laczenie z Telegram Web...")
        state, error = login.wait_for_state(self.driver, None, timeout=45)
        if state == "qr":
            state, error = login.open_phone_form(self.driver)
        self._set_busy(False)
        self._report_state(state, error)
        if state == "logged_in":
            self.log("Zalogowano (zapisana sesja).")

    def cmd_phone(self, phone):
        self._set_busy(True, "Wysylanie numeru...")
        state, error = login.submit_phone(self.driver, phone)
        self._set_busy(False)
        self._report_state(state, error)
        if state == "code":
            self.log("Telegram wyslal kod do aplikacji Telegram na Twoim telefonie/komputerze.")

    def cmd_code(self, code):
        self._set_busy(True, "Sprawdzanie kodu...")
        state, error = login.submit_code(self.driver, code)
        self._set_busy(False)
        self._report_state(state, error)

    def cmd_password(self, password):
        self._set_busy(True, "Sprawdzanie hasla 2FA...")
        state, error = login.submit_password(self.driver, password)
        self._set_busy(False)
        self._report_state(state, error)

    def cmd_refresh_state(self):
        if self.driver:
            self._report_state(*login.get_state(self.driver))

    def cmd_scan(self):
        if not self.driver:
            return
        self._set_busy(True, "Skanowanie czatów...")
        self.log("Skanowanie czatów...")
        started = time.time()
        try:
            for attempt in range(3):
                try:
                    result = telegram_api.scan(self.driver)
                    break
                except telegram_api.TelegramApiError as err:
                    if attempt == 2:
                        raise
                    self.log(f"Telegram Web jeszcze się ładuje ({err}), ponawiam...")
                    time.sleep(3)
            groups = result["groups"]
            writable = sum(sum(t["can_send"] for t in g["topics"]) if g["topics"] else int(g["can_send"])
                           for g in groups)
            self.log(f"Gotowe w {time.time() - started:.1f} s: {len(groups)} grup/kanałów, "
                     f"{writable} miejsc do pisania, {len(result['privates'])} czatów prywatnych.")
            for g in groups:
                if g["topics"]:
                    ok = sum(1 for t in g["topics"] if t["can_send"])
                    self.log(f"   forum '{g['name']}': {ok}/{len(g['topics'])} tematów otwartych do pisania")
                elif not g["can_send"]:
                    self.log(f"   pominięto '{g['name']}': {g['reason']}")
            self.emit("scan", result)
        finally:
            self._set_busy(False)

    def cmd_history(self, peer_id):
        if not self.driver:
            return
        self._set_busy(True, "Wczytywanie wiadomości...")
        try:
            self.emit("history", {"peer_id": peer_id, "messages": telegram_api.history(self.driver, peer_id, 40)})
        finally:
            self._set_busy(False)

    def cmd_test_send(self, target):
        """Send once to a single target right now (used by the 'Wyślij test' button)."""
        if not self.driver:
            return
        from telegram_scheduler import send_to_target
        self._set_busy(True, "Wysyłanie testowe...")
        try:
            send_to_target(self.driver, target, self.settings)
            self.log(f"Wyslano do: {target['name']} (test)")
        except Exception as err:
            self.log(f"Blad wysylki do '{target['name']}': {err}")
        finally:
            self._set_busy(False)

    def cmd_start_sending(self, targets):
        if not self.driver:
            return
        self.scheduler = Scheduler(targets, self.settings, self.log)
        self.log(f"Start wysylania do {len(targets)} czatow.")
        self.emit("sending", True)
        self.emit("schedule", self.scheduler.snapshot())

    def cmd_stop_sending(self):
        if self.scheduler:
            self.scheduler = None
            self.log("Wysylanie zatrzymane.")
        self.emit("sending", False)
        self.emit("schedule", [])

    def cmd_send_now(self):
        if self.scheduler:
            for key in self.scheduler.next_send:
                self.scheduler.next_send[key] = 0

    def cmd_screenshot(self, path):
        if self.driver:
            self.driver.save_screenshot(path)
            self.log(f"Zapisano zrzut ekranu przegladarki: {path}")

    def cmd_logout(self):
        self.scheduler = None
        self.emit("sending", False)
        self._quit_driver()
        shutil.rmtree(profile_dir(), ignore_errors=True)
        self.log("Usunieto zapisana sesje. Uruchamiam ponownie...")
        self.cmd_start()
