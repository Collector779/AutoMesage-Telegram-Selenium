"""Per-chat randomized sending schedule, advanced in small ticks by the worker thread."""
import random
import time

import telegram_api

SLOWMODE_MARGIN_S = 3   # send this many seconds after the slow-mode window ends
FLOOD_MARGIN_S = 5


def send_to_target(driver, target, settings):
    """Send the configured content (own text or a forwarded message) to one target."""
    if settings.get("mode") == "forward":
        fwd = settings.get("forward") or {}
        if not fwd.get("mid"):
            raise RuntimeError("nie wybrano wiadomości do przekazania")
        telegram_api.forward(driver, target["peer_id"], target.get("thread_id"),
                             fwd["from_peer_id"], fwd["mid"], fwd.get("drop_author", False))
    else:
        text = settings.get("message", "")
        if not text.strip():
            raise RuntimeError("pusta treść wiadomości")
        telegram_api.send_text(driver, target["peer_id"], target.get("thread_id"), text)


def fmt_wait(seconds):
    seconds = int(seconds)
    if seconds < 90:
        return f"{seconds} s"
    if seconds < 3600:
        return f"{seconds // 60} min {seconds % 60:02d} s"
    return f"{seconds // 3600} h {seconds % 3600 // 60:02d} min"


class Scheduler:
    def __init__(self, targets, settings, log):
        self.targets = {t["key"]: t for t in targets}
        self.settings = settings
        self.log = log
        lo, hi = int(settings["first_delay_min_s"]), int(settings["first_delay_max_s"])
        now = time.time()
        self.next_send = {k: now + random.randint(min(lo, hi), max(lo, hi)) for k in self.targets}
        self.sent_count = {k: 0 for k in self.targets}
        self.note = {k: "" for k in self.targets}  # "" | "slowmode" | "flood" | "error"
        # learned slow-mode length per group (peer_id -> seconds), seeded from the scan
        self.slowmode = {t["peer_id"]: int(t.get("slowmode") or 0) for t in targets}

    def _next_interval(self, peer_id):
        lo, hi = int(self.settings["interval_min_min"]), int(self.settings["interval_max_min"])
        interval = random.randint(min(lo, hi) * 60, max(lo, hi) * 60)
        # never schedule faster than the group's slow mode allows
        return max(interval, self.slowmode.get(peer_id, 0) + SLOWMODE_MARGIN_S)

    def _postpone(self, key, seconds, note):
        self.next_send[key] = time.time() + seconds
        self.note[key] = note

    def _slowmode_left(self, driver, target):
        """Ask Telegram how long the slow mode still blocks this group (0 = can post now)."""
        if not self.slowmode.get(target["peer_id"]):
            return 0
        try:
            seconds, wait = telegram_api.slowmode(driver, target["peer_id"])
        except Exception:
            return 0  # unknown: just try, the server will tell us via SLOWMODE_WAIT_X
        self.slowmode[target["peer_id"]] = seconds
        return wait

    def tick(self, driver):
        """Send to every target whose time has come."""
        for key, target in self.targets.items():
            if time.time() < self.next_send[key]:
                continue
            name = target["name"]

            wait = self._slowmode_left(driver, target)
            if wait > 0:
                self._postpone(key, wait + SLOWMODE_MARGIN_S, "slowmode")
                self.log(f"Tryb powolny w '{name}': wolno pisać za {fmt_wait(wait)}, wtedy wyślę.")
                continue

            try:
                send_to_target(driver, target, self.settings)
            except telegram_api.TelegramApiError as err:
                wait = err.wait_seconds
                if err.is_slowmode:
                    if wait is None:
                        wait = self.slowmode.get(target["peer_id"]) or 60
                    self.slowmode[target["peer_id"]] = max(self.slowmode.get(target["peer_id"], 0), wait)
                    self._postpone(key, wait + SLOWMODE_MARGIN_S, "slowmode")
                    self.log(f"Tryb powolny w '{name}': Telegram każe czekać {fmt_wait(wait)}, "
                             f"wyślę zaraz potem.")
                elif err.is_flood and wait is not None:
                    # account-wide limit: hold back every target, not just this one
                    until = time.time() + wait + FLOOD_MARGIN_S
                    for k in self.targets:
                        if self.next_send[k] < until:
                            self.next_send[k] = until
                            self.note[k] = "flood"
                    self.log(f"Limit Telegrama (FLOOD_WAIT): wstrzymuję wysyłanie na {fmt_wait(wait)}.")
                else:
                    self._fail(key, name, err)
                continue
            except Exception as err:
                self._fail(key, name, err)
                continue

            self.sent_count[key] += 1
            self._postpone(key, self._next_interval(target["peer_id"]), "")
            self.log(f"Wyslano do: {name}")

    def _fail(self, key, name, err):
        retry = int(self.settings["retry_after_error_min"]) * 60
        self._postpone(key, retry, "error")
        self.log(f"Blad wysylki do '{name}': {err}. Ponowna proba za {retry // 60} min.")

    def snapshot(self):
        return [
            {"key": k, "name": t["name"], "next": self.next_send[k], "sent": self.sent_count[k],
             "note": self.note[k]}
            for k, t in self.targets.items()
        ]
