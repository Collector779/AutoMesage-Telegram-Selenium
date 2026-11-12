"""Per-chat randomized sending schedule, advanced in small ticks by the worker thread."""
import random
import time

import telegram_api


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


class Scheduler:
    def __init__(self, targets, settings, log):
        self.targets = {t["key"]: t for t in targets}
        self.settings = settings
        self.log = log
        lo, hi = int(settings["first_delay_min_s"]), int(settings["first_delay_max_s"])
        now = time.time()
        self.next_send = {k: now + random.randint(min(lo, hi), max(lo, hi)) for k in self.targets}
        self.sent_count = {k: 0 for k in self.targets}

    def _next_interval(self):
        lo, hi = int(self.settings["interval_min_min"]), int(self.settings["interval_max_min"])
        return random.randint(min(lo, hi) * 60, max(lo, hi) * 60)

    def tick(self, driver):
        """Send to every target whose time has come."""
        for key, target in self.targets.items():
            if time.time() < self.next_send[key]:
                continue
            try:
                send_to_target(driver, target, self.settings)
                self.sent_count[key] += 1
                self.next_send[key] = time.time() + self._next_interval()
                self.log(f"Wyslano do: {target['name']}")
            except Exception as err:
                retry = int(self.settings["retry_after_error_min"]) * 60
                self.next_send[key] = time.time() + retry
                self.log(f"Blad wysylki do '{target['name']}': {err}. Ponowna proba za {retry // 60} min.")

    def snapshot(self):
        return [
            {"key": k, "name": t["name"], "next": self.next_send[k], "sent": self.sent_count[k]}
            for k, t in self.targets.items()
        ]
