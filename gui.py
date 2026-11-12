"""ttkbootstrap window: login by phone + code, chat tree, message / forward picker, sending control."""
import os
import queue
import subprocess
import time
import tkinter as tk
from datetime import datetime
from tkinter import filedialog

import threading

import ttkbootstrap as tb

from config import APP_VERSION, ASSETS_DIR, DEFAULT_SETTINGS, app_data_dir, load_settings, save_settings
from proxy_relay import test_proxy
from telegram_browser import proxy_url
from worker import BrowserWorker

PROXY_TYPES = [("HTTP", "http"), ("HTTPS", "https"), ("SOCKS5", "socks5"), ("SOCKS4", "socks4")]

BOX_ON, BOX_OFF, BOX_PART, BOX_NONE = "\u2611", "\u2610", "\u25a3", "\u2012"
ICONS = {"channel": "\U0001F4E2", "group": "\U0001F465", "forum": "\U0001F4AC", "topic": "#"}
KIND_LABEL = {"channel": "Kanał", "group": "Grupa", "forum": "Forum"}
DEFAULT_THEME = "tokyo-night-dark"
THEMES = [
    ("Tokyo Night (ciemny)", "tokyo-night-dark"),
    ("Nord (ciemny)", "nord-dark"),
    ("Dracula (ciemny)", "dracula-dark"),
    ("Catppuccin (ciemny)", "catppuccin-dark"),
    ("Bootstrap (ciemny)", "bootstrap-dark"),
    ("Bootstrap (jasny)", "bootstrap-light"),
    ("Minty (jasny)", "minty-light"),
    ("Nord (jasny)", "nord-light"),
    ("Pulse (jasny)", "pulse-light"),
]


def topic_key(peer_id, thread_id):
    return f"{peer_id}_{thread_id}"


def fmt_date(ts):
    try:
        return datetime.fromtimestamp(int(ts)).strftime("%d.%m %H:%M")
    except (TypeError, ValueError, OSError):
        return ""


class App:
    def __init__(self, root: tb.Window):
        self.root = root
        self.settings = load_settings()
        self.events = queue.Queue()
        self.worker = BrowserWorker(self.events, self.settings)
        self.scan_data = self.settings.get("scan") or {}
        self.selected = set(self.settings.get("selected", []))
        self.schedule = {}
        self.history = []
        self.logged_in = False
        self.sending = False
        self.busy = False
        self._replace_line = False
        self._targets = {}  # key -> target dict for every writable place

        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self._apply_theme(self.settings.get("theme", DEFAULT_THEME))

        self._build_menu()
        self._build_header()
        self._build_actions()  # packed at the bottom first so it never gets squeezed out
        self._build_login()
        self._build_main()
        self._rebuild_targets()
        self._refresh_tree()
        self._refresh_sources()
        self._show_mode()
        self._update_controls()

        self.worker.start()
        self.worker.send("start")
        self.root.after(100, self._poll_events)
        self.root.after(1000, self._tick_clock)

    # ---------------------------------------------------------------- dialogs
    def ask(self, title, message):
        res = tb.Messagebox.yesno(message, title, parent=self.root, localize=False,
                                  buttons=["Nie:secondary", "Tak:primary"])
        return res == "Tak"

    def info(self, title, message):
        tb.Messagebox.ok(message, title, parent=self.root, localize=False, buttons=["OK:primary"])

    def toast(self, title, message, style="success"):
        try:
            tb.ToastNotification(title, message, duration=4000, bootstyle=style).show_toast()
        except Exception:
            pass

    # ---------------------------------------------------------------- theme
    def _apply_theme(self, name):
        try:
            self.root.theme_use(name)
        except Exception:
            name = DEFAULT_THEME
            self.root.theme_use(name)
        self.settings["theme"] = name
        style = self.root.style
        style.configure("Treeview", rowheight=30)
        style.configure("Treeview.Heading", font=("TkDefaultFont", 10, "bold"))

    def change_theme(self):
        self._apply_theme(self.theme_var.get())
        save_settings(self.settings)

    # ---------------------------------------------------------------- layout
    def _build_menu(self):
        menubar = tk.Menu(self.root)

        m_file = tk.Menu(menubar, tearoff=False)
        m_file.add_command(label="Ustawienia (proxy, przeglądarka)...", command=self.open_settings,
                           accelerator="Ctrl+,")
        m_file.add_command(label="Zapisz ustawienia", command=self.save, accelerator="Ctrl+S")
        m_file.add_command(label="Otwórz folder danych", command=self.open_data_dir)
        m_file.add_separator()
        m_file.add_command(label="Zakończ", command=self.on_close)
        menubar.add_cascade(label="Plik", menu=m_file)

        m_acc = tk.Menu(menubar, tearoff=False)
        m_acc.add_command(label="Połącz ponownie", command=lambda: self.worker.send("start"))
        m_acc.add_command(label="Wyloguj (usuń zapisaną sesję)", command=self.logout)
        menubar.add_cascade(label="Konto", menu=m_acc)

        m_tools = tk.Menu(menubar, tearoff=False)
        m_tools.add_command(label="Skanuj czaty", command=self.scan)
        m_tools.add_separator()
        m_tools.add_command(label="Sprawdź IP przeglądarki", command=self.check_ip)
        m_tools.add_command(label="Zrzut ekranu przeglądarki...", command=self.screenshot)
        menubar.add_cascade(label="Narzędzia", menu=m_tools)

        m_view = tk.Menu(menubar, tearoff=False)
        self.theme_var = tk.StringVar(value=self.settings["theme"])
        for label, name in THEMES:
            m_view.add_radiobutton(label=label, value=name, variable=self.theme_var, command=self.change_theme)
        menubar.add_cascade(label="Wygląd", menu=m_view)

        m_help = tk.Menu(menubar, tearoff=False)
        m_help.add_command(label="O programie", command=self.about)
        menubar.add_cascade(label="Pomoc", menu=m_help)

        self.root.config(menu=menubar)
        self.root.bind_all("<Control-s>", lambda e: self.save())
        self.root.bind_all("<Control-comma>", lambda e: self.open_settings())

    def _build_header(self):
        head = tb.Frame(self.root, padding=(20, 16, 20, 8))
        head.pack(fill="x")
        left = tb.Frame(head)
        left.pack(side="left")
        tb.Label(left, text="\u2708  Telegram AutoMessage", font=("TkDefaultFont", 18, "bold"),
                 bootstyle="primary").pack(anchor="w")
        tb.Label(left, text="Automatyczne wiadomości do grup i kanałów, w tle",
                 bootstyle="secondary").pack(anchor="w")

        right = tb.Frame(head)
        right.pack(side="right")
        self.status_var = tk.StringVar(value="Uruchamianie...")
        self.status_pill = tb.Label(right, textvariable=self.status_var, bootstyle="@info",
                                    padding=(12, 4), font=("TkDefaultFont", 10, "bold"))
        self.status_pill.pack(anchor="e")
        self.proxy_var = tk.StringVar()
        self.proxy_label = tb.Label(right, textvariable=self.proxy_var, bootstyle="info", cursor="hand2")
        self.proxy_label.bind("<Button-1>", lambda e: self.open_settings())
        self._update_proxy_label()
        self.progress =tb.Progressbar(right, mode="indeterminate", length=180, bootstyle="striped info")
        self.busy_var = tk.StringVar()
        self.busy_label = tb.Label(right, textvariable=self.busy_var, bootstyle="secondary")

        tb.Separator(self.root).pack(fill="x", padx=20)

    def _show_busy(self, text):
        self.busy_var.set(text)
        self.busy_label.pack(anchor="e", pady=(6, 0))
        self.progress.pack(anchor="e", pady=(4, 0))
        self.progress.start(12)

    def _hide_busy(self):
        self.progress.stop()
        self.progress.pack_forget()
        self.busy_label.pack_forget()

    def _set_status(self, text, style="info"):
        self.status_var.set(text)
        try:
            self.status_pill.configure(bootstyle=f"@{style}")
        except Exception:
            pass

    def _build_login(self):
        self.login_frame = tb.Labelframe(self.root, text="  Logowanie do Telegrama  ", padding=20,
                                         bootstyle="primary")
        self.login_hint = tk.StringVar()
        tb.Label(self.login_frame, textvariable=self.login_hint, wraplength=760,
                 font=("TkDefaultFont", 10)).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 12))

        self.phone_var, self.code_var, self.pass_var = tk.StringVar(), tk.StringVar(), tk.StringVar()
        self.login_rows = {}
        for row, (key, label, var, cmd, show) in enumerate([
            ("phone", "Numer telefonu", self.phone_var, self.submit_phone, ""),
            ("code", "Kod z aplikacji", self.code_var, self.submit_code, ""),
            ("password", "Hasło 2FA", self.pass_var, self.submit_password, "\u2022"),
        ], start=1):
            lbl = tb.Label(self.login_frame, text=label, font=("TkDefaultFont", 10, "bold"))
            ent = tb.Entry(self.login_frame, textvariable=var, width=26, show=show,
                           font=("TkDefaultFont", 13), bootstyle="primary")
            btn = tb.Button(self.login_frame, text="Dalej  \u2192", command=cmd, bootstyle="primary", width=12)
            ent.bind("<Return>", lambda e, c=cmd: c())
            self.login_rows[key] = (row, lbl, ent, btn)

        self.login_error = tk.StringVar()
        tb.Label(self.login_frame, textvariable=self.login_error, bootstyle="danger").grid(
            row=5, column=0, columnspan=3, sticky="w", pady=(10, 0))

    def _show_login(self, step):
        for key, (row, lbl, ent, btn) in self.login_rows.items():
            if key == step:
                lbl.grid(row=row, column=0, sticky="w", padx=(0, 12))
                ent.grid(row=row, column=1, sticky="w", ipady=4)
                btn.grid(row=row, column=2, padx=12)
                ent.focus_set()
            else:
                lbl.grid_remove(); ent.grid_remove(); btn.grid_remove()
        if not self.login_frame.winfo_ismapped():
            self.login_frame.pack(fill="x", padx=20, pady=(14, 0), before=self.notebook)

    def _hide_login(self):
        self.login_frame.pack_forget()

    def _build_main(self):
        self.notebook = tb.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=20, pady=(14, 0))
        self._build_chats_tab()
        self._build_message_tab()
        self._build_log_tab()

    def _build_chats_tab(self):
        tab = tb.Frame(self.notebook, padding=14)
        self.notebook.add(tab, text="  Czaty  ")
        top = tb.Frame(tab)
        top.pack(fill="x", pady=(0, 10))
        self.btn_scan = tb.Button(top, text="\u27f3  Skanuj czaty", bootstyle="info", command=self.scan)
        self.btn_scan.pack(side="left")
        tb.Button(top, text="Zaznacz wszystkie", bootstyle="secondary outline",
                  command=lambda: self.select_all(True)).pack(side="left", padx=(10, 4))
        tb.Button(top, text="Odznacz", bootstyle="secondary outline",
                  command=lambda: self.select_all(False)).pack(side="left")
        self.show_unavail = tk.BooleanVar(value=bool(self.settings.get("show_unavailable")))
        tb.Checkbutton(top, text="Pokaż niedostępne", variable=self.show_unavail, bootstyle="toggle",
                       command=self._on_show_unavail).pack(side="left", padx=(16, 0))
        self.filter_var = tk.StringVar()
        self.filter_var.trace_add("write", lambda *a: self._refresh_tree())
        tb.Entry(top, textvariable=self.filter_var, width=22).pack(side="right")
        tb.Label(top, text="\U0001F50E", font=("TkDefaultFont", 11)).pack(side="right", padx=6)

        tree_frame = tb.Frame(tab)
        tree_frame.pack(fill="both", expand=True)
        self.tree = tb.Treeview(tree_frame, columns=("type", "next", "sent"), show="tree headings",
                                selectmode="none", bootstyle="primary")
        self.tree.heading("#0", text="  Grupa / kanał / temat", anchor="w")
        self.tree.column("#0", width=380, minwidth=220, stretch=True)
        for col, text, width, anchor in [("type", "Typ / status", 200, "w"),
                                          ("next", "Następna", 120, "center"),
                                          ("sent", "Wysłano", 90, "center")]:
            self.tree.heading(col, text=text, anchor=anchor)
            self.tree.column(col, width=width, anchor=anchor, stretch=False)
        self.tree.tag_configure("off", foreground="#7f849c")
        self.tree.tag_configure("parent", font=("TkDefaultFont", 10, "bold"))
        sb = tb.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview, bootstyle="round")
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.bind("<Button-1>", self._on_tree_click)
        self.tree.bind("<space>", self._on_tree_space)
        self.empty_hint = tb.Label(tab, text="Brak czatów. Zaloguj się i kliknij \u201eSkanuj czaty\u201d.",
                                   bootstyle="secondary")
        legend = tb.Frame(tab)
        legend.pack(fill="x", pady=(8, 0))
        self.count_var = tk.StringVar()
        tb.Label(legend, textvariable=self.count_var, bootstyle="secondary").pack(side="left")
        tb.Label(legend, bootstyle="secondary",
                 text=f"{ICONS['channel']} kanał   {ICONS['group']} grupa   {ICONS['forum']} forum z tematami   "
                      f"#  temat").pack(side="right")

    def _build_message_tab(self):
        tab = tb.Frame(self.notebook, padding=14)
        self.notebook.add(tab, text="  Wiadomość  ")

        modes = tb.Frame(tab)
        modes.pack(fill="x", pady=(0, 10))
        tb.Label(modes, text="Co wysyłać:", font=("TkDefaultFont", 11, "bold")).pack(side="left", padx=(0, 10))
        self.mode_var = tk.StringVar(value=self.settings.get("mode", "text"))
        for value, text in (("text", "\u270d  Własna treść"), ("forward", "\u21aa  Przekaż wiadomość z czatu")):
            tb.Radiobutton(modes, text=text, value=value, variable=self.mode_var, bootstyle="primary toolbutton",
                           command=self._show_mode, padding=(12, 6)).pack(side="left", padx=2)

        # bottom part (schedule + save) is packed first so the content above shrinks instead
        bottom = tb.Frame(tab)
        bottom.pack(side="bottom", fill="x")
        sched = tb.Labelframe(bottom, text="  Harmonogram  ", padding=14, bootstyle="info")
        sched.pack(fill="x", pady=(10, 0))
        self.spin_vars = {}
        rows = [
            ("Pierwsza wysyłka po", "first_delay_min_s", "first_delay_max_s", "sekund", 0, 86400),
            ("Kolejne wysyłki co", "interval_min_min", "interval_max_min", "minut", 1, 10080),
        ]
        for r, (label, k_lo, k_hi, unit, lo, hi) in enumerate(rows):
            tb.Label(sched, text=label).grid(row=r, column=0, sticky="w", pady=4, padx=(0, 10))
            for c, key in ((1, k_lo), (3, k_hi)):
                var = tk.IntVar(value=int(self.settings.get(key, 0)))
                self.spin_vars[key] = var
                tb.Spinbox(sched, from_=lo, to=hi, textvariable=var, width=7).grid(row=r, column=c, sticky="w")
            tb.Label(sched, text="–").grid(row=r, column=2, padx=6)
            tb.Label(sched, text=f"{unit} (losowo)", bootstyle="secondary").grid(row=r, column=4, sticky="w", padx=8)
        tb.Label(sched, text="Po błędzie ponów za").grid(row=2, column=0, sticky="w", pady=4)
        var = tk.IntVar(value=int(self.settings.get("retry_after_error_min", 30)))
        self.spin_vars["retry_after_error_min"] = var
        tb.Spinbox(sched, from_=1, to=1440, textvariable=var, width=7).grid(row=2, column=1, sticky="w")
        tb.Label(sched, text="minut", bootstyle="secondary").grid(row=2, column=2, columnspan=3, sticky="w", padx=6)
        tb.Button(bottom, text="Zapisz", bootstyle="primary outline", command=self.save).pack(anchor="e", pady=(10, 0))

        # --- mode: own text
        self.text_frame = tb.Frame(tab)
        tb.Label(self.text_frame, text="Enter = nowa linia. Emoji i polskie znaki działają.",
                 bootstyle="secondary").pack(anchor="w", pady=(0, 6))
        self.msg_count = tk.StringVar()
        tb.Label(self.text_frame, textvariable=self.msg_count, bootstyle="secondary").pack(side="bottom", anchor="e",
                                                                                         pady=(4, 0))
        msg_frame = tb.Frame(self.text_frame)
        msg_frame.pack(fill="both", expand=True)
        self.msg_text = tb.Text(msg_frame, height=6, wrap="word", undo=True, font=("TkDefaultFont", 11),
                                padx=10, pady=8)
        msb = tb.Scrollbar(msg_frame, orient="vertical", command=self.msg_text.yview, bootstyle="round")
        self.msg_text.configure(yscrollcommand=msb.set)
        self.msg_text.pack(side="left", fill="both", expand=True)
        msb.pack(side="right", fill="y")
        self.msg_text.insert("1.0", self.settings.get("message", ""))
        self.msg_text.bind("<<Modified>>", self._on_msg_modified)
        self._on_msg_modified()

        # --- mode: forward
        self.fwd_frame = tb.Frame(tab)
        src_row = tb.Frame(self.fwd_frame)
        src_row.pack(fill="x", pady=(0, 8))
        tb.Label(src_row, text="Z czatu:").pack(side="left", padx=(0, 8))
        self.source_var = tk.StringVar()
        self.source_box = tb.Combobox(src_row, textvariable=self.source_var, state="readonly", width=34)
        self.source_box.pack(side="left")
        self.source_box.bind("<<ComboboxSelected>>", lambda e: self.load_history())
        self.btn_load = tb.Button(src_row, text="\u27f3  Wczytaj wiadomości", bootstyle="info outline",
                                  command=self.load_history)
        self.btn_load.pack(side="left", padx=8)
        fwd = self.settings.get("forward") or {}
        self.drop_author = tk.BooleanVar(value=bool(fwd.get("drop_author")))
        tb.Checkbutton(src_row, text="Ukryj \u201ePrzekazano od\u201d", variable=self.drop_author,
                       bootstyle="toggle", command=self._on_drop_author).pack(side="right")

        self.fwd_selected = tk.StringVar()
        tb.Label(self.fwd_frame, textvariable=self.fwd_selected, bootstyle="success",
                 wraplength=860).pack(side="bottom", anchor="w", pady=(8, 0))
        hist_frame = tb.Frame(self.fwd_frame)
        hist_frame.pack(fill="both", expand=True)
        self.hist = tb.Treeview(hist_frame, columns=("date", "text"), show="headings", selectmode="browse",
                                bootstyle="info", height=6)
        self.hist.heading("date", text="Data", anchor="w")
        self.hist.heading("text", text="Wiadomość (kliknij, aby wybrać)", anchor="w")
        self.hist.column("date", width=110, stretch=False)
        self.hist.column("text", width=600, stretch=True)
        hsb = tb.Scrollbar(hist_frame, orient="vertical", command=self.hist.yview, bootstyle="round")
        self.hist.configure(yscrollcommand=hsb.set)
        self.hist.pack(side="left", fill="both", expand=True)
        hsb.pack(side="right", fill="y")
        self.hist.bind("<<TreeviewSelect>>", self._on_hist_select)
        self._update_fwd_label()

    def _build_log_tab(self):
        tab = tb.Frame(self.notebook, padding=14)
        self.notebook.add(tab, text="  Log  ")
        log_frame = tb.Frame(tab)
        log_frame.pack(fill="both", expand=True)
        self.log_text = tb.Text(log_frame, height=10, state="disabled", wrap="word",
                                font=("Consolas" if os.name == "nt" else "Monospace", 9), padx=8, pady=6)
        lsb = tb.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview, bootstyle="round")
        self.log_text.configure(yscrollcommand=lsb.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        lsb.pack(side="right", fill="y")

    def _build_actions(self):
        bar = tb.Frame(self.root, padding=(20, 14, 20, 18))
        bar.pack(side="bottom", fill="x")
        self.btn_start = tb.Button(bar, text="\u25b6   Start wysyłania", bootstyle="success",
                                   command=self.start_sending, width=20)
        self.btn_start.pack(side="left", ipady=4)
        self.btn_stop = tb.Button(bar, text="\u25a0   Stop", bootstyle="danger outline",
                                  command=lambda: self.worker.send("stop_sending"), width=10)
        self.btn_stop.pack(side="left", padx=10, ipady=4)
        self.btn_now = tb.Button(bar, text="Wyślij teraz", bootstyle="secondary outline", command=self.send_now)
        self.btn_now.pack(side="left", ipady=4)
        self.btn_test = tb.Button(bar, text="Wyślij test\u2026", bootstyle="secondary outline", command=self.test_send)
        self.btn_test.pack(side="left", padx=10, ipady=4)
        self.summary_var = tk.StringVar()
        tb.Label(bar, textvariable=self.summary_var, bootstyle="secondary").pack(side="right")

    # ---------------------------------------------------------------- chat tree
    def _rebuild_targets(self):
        self._targets = {}
        for g in self.scan_data.get("groups", []):
            if g["topics"]:
                for t in g["topics"]:
                    if t["can_send"]:
                        key = topic_key(g["peer_id"], t["thread_id"])
                        self._targets[key] = {"key": key, "peer_id": g["peer_id"], "thread_id": t["thread_id"],
                                              "name": f"{g['name']} / {t['name']}",
                                              "slowmode": g.get("slowmode", 0)}
            elif g["can_send"]:
                self._targets[g["peer_id"]] = {"key": g["peer_id"], "peer_id": g["peer_id"], "thread_id": None,
                                               "name": g["name"], "slowmode": g.get("slowmode", 0)}
        self.selected &= set(self._targets)

    def _group_children_keys(self, g):
        return [topic_key(g["peer_id"], t["thread_id"]) for t in g["topics"] if t["can_send"]]

    def _schedule_cells(self, key):
        sched = self.schedule.get(key)
        if not sched:
            return "–", ""
        left = max(0, int(sched["next"] - time.time()))
        nxt = f"za {left // 3600}h {left % 3600 // 60:02d}m {left % 60:02d}s" if left else "teraz"
        icon = {"slowmode": "  ⏳", "flood": "  ⏸", "error": "  ⚠"}.get(sched.get("note"), "")
        return nxt + icon, sched["sent"]

    def _refresh_tree(self):
        open_items = {iid for iid in self.tree.get_children() if self.tree.item(iid, "open")}
        first_fill = not self.tree.get_children()
        self.tree.delete(*self.tree.get_children())
        flt = self.filter_var.get().strip().lower()
        show_off = self.show_unavail.get()
        groups = self.scan_data.get("groups", [])
        # writable first, then the rest; inside each, keep Telegram's order
        groups = sorted(groups, key=lambda g: not (g["can_send"] and (not g["topics"] or
                                                                         any(t["can_send"] for t in g["topics"]))))
        for g in groups:
            topics = g["topics"]
            open_topics = [t for t in topics if t["can_send"]]
            usable = bool(open_topics) if topics else g["can_send"]
            name_hit = not flt or flt in g["name"].lower()
            shown_topics = [t for t in topics if (show_off or t["can_send"]) and
                            (name_hit or flt in t["name"].lower())]
            if not usable and not show_off:
                continue
            if not name_hit and not shown_topics:
                continue
            arch = "  \u2022 archiwum" if g.get("archived") else ""
            if topics:
                kids = self._group_children_keys(g)
                chosen = sum(k in self.selected for k in kids)
                box = BOX_NONE if not kids else BOX_ON if chosen == len(kids) else BOX_PART if chosen else BOX_OFF
                sm = int(g.get("slowmode") or 0)
                slow = ("" if not sm else "  • ⏳" +
                        (f" {sm // 60} min" if sm >= 60 else f" {sm} s" if sm > 1 else ""))
                status = (f"Forum \u2022 {len(open_topics)}/{len(topics)} tematów{slow}" if usable
                          else f"Forum \u2022 {g['reason'] or 'wszystkie tematy zamknięte'}")
                iid = f"g:{g['peer_id']}"
                self.tree.insert("", "end", iid=iid, text=f" {box}  {ICONS['forum']}  {g['name']}",
                                 values=(status + arch, "", ""), open=(iid in open_items or first_fill or bool(flt)),
                                 tags=("parent",) if usable else ("parent", "off"))
                for t in shown_topics:
                    key = topic_key(g["peer_id"], t["thread_id"])
                    if t["can_send"]:
                        tb_ = BOX_ON if key in self.selected else BOX_OFF
                        self.tree.insert(iid, "end", iid=key, text=f" {tb_}  #  {t['name']}",
                                         values=("Temat", *self._schedule_cells(key)))
                    else:
                        self.tree.insert(iid, "end", iid=f"x:{key}", text=f" {BOX_NONE}  #  {t['name']}",
                                         values=(f"Temat \u2022 {t['reason']}", "", ""), tags=("off",))
            else:
                kind = KIND_LABEL.get(g["kind"], "Grupa")
                if g["can_send"]:
                    key = g["peer_id"]
                    box = BOX_ON if key in self.selected else BOX_OFF
                    sm = int(g.get("slowmode") or 0)
                    slow = ("" if not sm else "  \u2022 \u23f3 tryb powolny" +
                            (f" {sm // 60} min" if sm >= 60 else f" {sm} s" if sm > 1 else ""))
                    self.tree.insert("", "end", iid=key, text=f" {box}  {ICONS.get(g['kind'], '')}  {g['name']}",
                                     values=(kind + slow + arch, *self._schedule_cells(key)))
                else:
                    self.tree.insert("", "end", iid=f"x:{g['peer_id']}",
                                     text=f" {BOX_NONE}  {ICONS.get(g['kind'], '')}  {g['name']}",
                                     values=(f"{kind} \u2022 {g['reason']}{arch}", "", ""), tags=("off",))
        if groups:
            self.empty_hint.place_forget()
        else:
            self.empty_hint.place(relx=0.5, rely=0.5, anchor="center")
        self._update_count()

    def _update_schedule_cells(self):
        for key in self._targets:
            if self.tree.exists(key):
                nxt, sent = self._schedule_cells(key)
                self.tree.set(key, "next", nxt)
                self.tree.set(key, "sent", sent)
        self._update_summary()

    def _update_count(self):
        self.count_var.set(f"{len(self._targets)} miejsc do pisania  \u2022  zaznaczono {len(self.selected)}")
        self._update_summary()

    def _update_summary(self):
        if self.sending and self.schedule:
            total = sum(s["sent"] for s in self.schedule.values())
            left = max(0, int(min(s["next"] for s in self.schedule.values()) - time.time()))
            self.summary_var.set(f"Wysłano: {total}   \u2022   najbliższa za {left // 60} min {left % 60:02d} s")
        else:
            self.summary_var.set(f"Zaznaczone: {len(self.selected)}")

    def _tick_clock(self):
        if self.sending:
            self._update_schedule_cells()
        self.root.after(1000, self._tick_clock)

    def _toggle(self, iid):
        if self.sending or iid.startswith("x:"):
            return
        if iid.startswith("g:"):
            peer = iid[2:]
            g = next((g for g in self.scan_data.get("groups", []) if g["peer_id"] == peer), None)
            kids = self._group_children_keys(g) if g else []
            if not kids:
                return
            if all(k in self.selected for k in kids):
                self.selected -= set(kids)
            else:
                self.selected |= set(kids)
        elif iid in self._targets:
            self.selected ^= {iid}
        self._refresh_tree()

    def _on_tree_click(self, event):
        region = self.tree.identify_region(event.x, event.y)
        iid = self.tree.identify_row(event.y)
        if not iid or region not in ("tree", "cell"):
            return
        if self.tree.identify_element(event.x, event.y).endswith("indicator"):
            return  # expand/collapse arrow
        self.tree.focus(iid)
        self._toggle(iid)
        return "break"

    def _on_tree_space(self, _event):
        iid = self.tree.focus()
        if iid:
            self._toggle(iid)

    def _on_show_unavail(self):
        self.settings["show_unavailable"] = self.show_unavail.get()
        self._refresh_tree()

    def select_all(self, on):
        if self.sending:
            return
        flt = self.filter_var.get().strip().lower()
        keys = {k for k, t in self._targets.items() if not flt or flt in t["name"].lower()}
        if on:
            self.selected |= keys
        else:
            self.selected -= keys
        self._refresh_tree()

    # ---------------------------------------------------------------- message / forward
    def _show_mode(self):
        if self.mode_var.get() == "forward":
            self.text_frame.pack_forget()
            self.fwd_frame.pack(fill="both", expand=True)
        else:
            self.fwd_frame.pack_forget()
            self.text_frame.pack(fill="both", expand=True)
        self.settings["mode"] = self.mode_var.get()

    def _on_msg_modified(self, _event=None):
        text = self.msg_text.get("1.0", "end-1c")
        self.msg_count.set(f"{len(text)} znaków")
        self.msg_text.edit_modified(False)

    def _sources(self):
        privates = self.scan_data.get("privates", [])
        my_id = self.scan_data.get("my_id")
        out = []
        if my_id:
            out.append({"peer_id": my_id, "name": "Zapisane wiadomości"})
        out += [p for p in privates if p["peer_id"] != my_id]
        return out

    def _source_label(self, p):
        return ("\U0001F516  " if p["name"] == "Zapisane wiadomości" else
                "\U0001F916  " if p.get("bot") else "\U0001F464  ") + p["name"]

    def _refresh_sources(self):
        srcs = self._sources()
        self.source_box.configure(values=[self._source_label(p) for p in srcs])
        fwd = self.settings.get("forward") or {}
        for p in srcs:
            if p["peer_id"] == fwd.get("from_peer_id"):
                self.source_var.set(self._source_label(p))
                break

    def _current_source(self):
        label = self.source_var.get()
        return next((p for p in self._sources() if self._source_label(p) == label), None)

    def load_history(self):
        src = self._current_source()
        if not src:
            self.info("Wybierz czat", "Najpierw wybierz czat, z którego chcesz przekazać wiadomość.")
            return
        if not self.logged_in:
            return
        self.worker.send("history", src["peer_id"])

    def _show_history(self, data):
        src = self._current_source()
        if not src or src["peer_id"] != data["peer_id"]:
            return
        self.history = data["messages"]
        self.hist.delete(*self.hist.get_children())
        fwd = self.settings.get("forward") or {}
        for m in self.history:
            text = m["text"].replace("\n", "  ")
            if m["media"]:
                text = f"[{m['media']}] {text}"
            if m["noforwards"]:
                text = "\u26d4 (nie można przekazać) " + text
            who = "Ty: " if m["out"] else ""
            self.hist.insert("", "end", iid=m["mid"], values=(fmt_date(m["date"]), who + (text or "(bez tekstu)")))
        if fwd.get("from_peer_id") == data["peer_id"] and self.hist.exists(str(fwd.get("mid"))):
            self.hist.selection_set(str(fwd["mid"]))
            self.hist.see(str(fwd["mid"]))
        if not self.history:
            self.fwd_selected.set("Ten czat nie ma wiadomości.")

    def _on_hist_select(self, _event=None):
        sel = self.hist.selection()
        src = self._current_source()
        if not sel or not src:
            return
        m = next((m for m in self.history if m["mid"] == sel[0]), None)
        if not m:
            return
        if m["noforwards"]:
            self.info("Nie można przekazać", "Ta wiadomość ma zablokowane przekazywanie.")
            return
        preview = (f"[{m['media']}] " if m["media"] else "") + (m["text"] or "")
        self.settings["forward"] = {"from_peer_id": src["peer_id"], "from_name": src["name"], "mid": m["mid"],
                                    "preview": preview[:200], "date": m["date"],
                                    "drop_author": self.drop_author.get()}
        self._update_fwd_label()

    def _on_drop_author(self):
        fwd = self.settings.get("forward") or {}
        fwd["drop_author"] = self.drop_author.get()
        self.settings["forward"] = fwd

    def _update_fwd_label(self):
        fwd = self.settings.get("forward") or {}
        if fwd.get("mid"):
            preview = " ".join((fwd.get("preview") or "(bez tekstu)").split())
            self.fwd_selected.set(f"\u2714 Wybrana: {fwd.get('from_name', '')}, {fmt_date(fwd.get('date'))} \u2013 "
                                  f"{preview[:110]}{'\u2026' if len(preview) > 110 else ''}")
        else:
            self.fwd_selected.set("Nie wybrano wiadomości. Wybierz czat, kliknij \u201eWczytaj\u201d i zaznacz "
                                  "wiadomość na liście.")

    # ---------------------------------------------------------------- actions
    def submit_phone(self):
        if self.phone_var.get().strip():
            self.worker.send("phone", self.phone_var.get().strip())

    def submit_code(self):
        if self.code_var.get().strip():
            self.worker.send("code", self.code_var.get().strip())

    def submit_password(self):
        if self.pass_var.get():
            self.worker.send("password", self.pass_var.get())
            self.pass_var.set("")

    def scan(self):
        if not self.logged_in or self.sending or self.busy:
            return
        self.worker.send("scan")

    def _collect_settings(self):
        self.settings["message"] = self.msg_text.get("1.0", "end-1c")
        self.settings["mode"] = self.mode_var.get()
        for key, var in self.spin_vars.items():
            try:
                self.settings[key] = max(0, int(var.get()))
            except (tk.TclError, ValueError):
                pass
        self.settings["selected"] = sorted(self.selected)
        self.settings["scan"] = self.scan_data
        self.settings.pop("chats", None)  # format of older versions

    def save(self):
        self._collect_settings()
        save_settings(self.settings)
        self._log("Zapisano ustawienia.")
        self.toast("Zapisano", "Ustawienia zostały zapisane.", "info")

    def _content_problem(self):
        if self.settings["mode"] == "forward":
            if not (self.settings.get("forward") or {}).get("mid"):
                return "Wybierz wiadomość do przekazania w zakładce \u201eWiadomość\u201d."
        elif not self.settings["message"].strip():
            return "Wpisz treść wiadomości w zakładce \u201eWiadomość\u201d."
        return None

    def _content_desc(self):
        if self.settings["mode"] == "forward":
            fwd = self.settings["forward"]
            preview = " ".join((fwd.get("preview") or "").split())
            return f"przekazanie wiadomości z \u201e{fwd.get('from_name')}\u201d:\n{preview[:80]}"
        return f"wiadomość:\n{self.settings['message'][:80]}"

    def start_sending(self):
        self._collect_settings()
        targets = [self._targets[k] for k in self._targets if k in self.selected]
        if not targets:
            self.info("Brak czatów", "Zaznacz przynajmniej jeden czat lub temat na liście.")
            return
        problem = self._content_problem()
        if problem:
            self.info("Brak treści", problem)
            return
        lo, hi = self.settings["interval_min_min"], self.settings["interval_max_min"]
        if not self.ask(
            "Start wysyłania",
            f"Do {len(targets)} miejsc zostanie wysłana {self._content_desc()}\n\n"
            f"Potem co {min(lo, hi)}–{max(lo, hi)} min, aż do zatrzymania. Zaczynamy?",
        ):
            return
        save_settings(self.settings)
        self.worker.send("start_sending", targets)
        self.notebook.select(0)

    def send_now(self):
        if self.sending and self.ask("Wyślij teraz", "Wysłać teraz do wszystkich zaznaczonych czatów?"):
            self.worker.send("send_now")

    def test_send(self):
        self._collect_settings()
        iid = self.tree.focus()
        target = self._targets.get(iid)
        if not target:
            self.info("Wyślij test", "Kliknij na liście czatów jeden czat lub temat, do którego wysłać test.")
            return
        problem = self._content_problem()
        if problem:
            self.info("Brak treści", problem)
            return
        if self.ask("Wyślij test", f"Wysłać teraz jeden raz do \u201e{target['name']}\u201d\n{self._content_desc()}"):
            self.worker.send("test_send", target)

    def screenshot(self):
        path = filedialog.asksaveasfilename(
            parent=self.root, defaultextension=".png",
            initialfile=f"telegram_{datetime.now():%Y%m%d_%H%M%S}.png", filetypes=[("PNG", "*.png")])
        if path:
            self.worker.send("screenshot", path)

    # ---------------------------------------------------------------- settings dialog
    def _update_proxy_label(self, ip=None):
        url = proxy_url(self.settings.get("proxy"))
        if url:
            host = url.split("://", 1)[1]
            self.proxy_var.set(f"\U0001F6E1  Proxy {host}" + (f"  •  IP {ip}" if ip else ""))
            self.proxy_label.pack(anchor="e", pady=(6, 0), after=self.status_pill)
        else:
            self.proxy_label.pack_forget()

    def check_ip(self):
        if self.logged_in or self.worker.driver:
            self.notebook.select(2)
            self.worker.send("check_ip")

    def open_settings(self):
        if getattr(self, "_settings_win", None) and self._settings_win.winfo_exists():
            self._settings_win.lift()
            return
        proxy = {**DEFAULT_SETTINGS["proxy"], **(self.settings.get("proxy") or {})}
        win = tb.Toplevel(title="Ustawienia")
        self._settings_win = win
        win.transient(self.root)
        win.resizable(False, False)
        body = tb.Frame(win, padding=20)
        body.pack(fill="both", expand=True)

        # --- proxy
        pf = tb.Labelframe(body, text="  Proxy  ", padding=16, bootstyle="primary")
        pf.pack(fill="x")
        v_on = tk.BooleanVar(value=bool(proxy.get("enabled")))
        v_type = tk.StringVar(value=next((l for l, k in PROXY_TYPES if k == proxy.get("type")), "HTTP"))
        v_host, v_port = tk.StringVar(value=proxy.get("host", "")), tk.StringVar(value=str(proxy.get("port", "")))
        v_user, v_pass = tk.StringVar(value=proxy.get("username", "")), tk.StringVar(value=proxy.get("password", ""))
        tb.Checkbutton(pf, text="Łącz z Telegramem przez proxy", variable=v_on, bootstyle="toggle").grid(
            row=0, column=0, columnspan=4, sticky="w", pady=(0, 12))
        tb.Label(pf, text="Typ").grid(row=1, column=0, sticky="w", pady=4)
        tb.Combobox(pf, textvariable=v_type, values=[l for l, _ in PROXY_TYPES], state="readonly",
                    width=10).grid(row=1, column=1, sticky="w", pady=4)
        tb.Label(pf, text="Adres").grid(row=2, column=0, sticky="w", pady=4)
        tb.Entry(pf, textvariable=v_host, width=30).grid(row=2, column=1, sticky="w", pady=4)
        tb.Label(pf, text="Port").grid(row=2, column=2, sticky="e", padx=(12, 6))
        tb.Entry(pf, textvariable=v_port, width=8).grid(row=2, column=3, sticky="w")
        tb.Label(pf, text="Login").grid(row=3, column=0, sticky="w", pady=4)
        tb.Entry(pf, textvariable=v_user, width=30).grid(row=3, column=1, sticky="w", pady=4)
        tb.Label(pf, text="Hasło").grid(row=4, column=0, sticky="w", pady=4)
        pass_entry = tb.Entry(pf, textvariable=v_pass, width=30, show="•")
        pass_entry.grid(row=4, column=1, sticky="w", pady=4)
        v_show = tk.BooleanVar(value=False)
        tb.Checkbutton(pf, text="pokaż", variable=v_show, bootstyle="secondary",
                       command=lambda: pass_entry.configure(show="" if v_show.get() else "•")).grid(
            row=4, column=2, columnspan=2, sticky="w", padx=(12, 0))
        tb.Label(pf, bootstyle="secondary", wraplength=440, justify="left",
                 text="Login i hasło są opcjonalne (działają dla HTTP, HTTPS i SOCKS5). "
                      "Hasło jest zapisywane w pliku ustawień na tym komputerze.").grid(
            row=5, column=0, columnspan=4, sticky="w", pady=(8, 0))

        test_row = tb.Frame(pf)
        test_row.grid(row=6, column=0, columnspan=4, sticky="w", pady=(12, 0))
        result = tk.StringVar()
        result_lbl = tb.Label(test_row, textvariable=result, wraplength=320)

        def collect():
            return {"enabled": v_on.get(), "type": dict(PROXY_TYPES).get(v_type.get(), "http"),
                    "host": v_host.get().strip(), "port": v_port.get().strip(),
                    "username": v_user.get().strip(), "password": v_pass.get()}

        def validate(p):
            if not p["enabled"]:
                return None
            if not p["host"]:
                return "Podaj adres proxy."
            if not p["port"].isdigit() or not 0 < int(p["port"]) < 65536:
                return "Port musi być liczbą od 1 do 65535."
            if p["type"] == "socks4" and p["password"]:
                return "SOCKS4 nie obsługuje hasła. Wybierz SOCKS5 albo HTTP."
            return None

        def run_test():
            p = {**collect(), "enabled": True}
            problem = validate(p)
            if problem:
                result.set("✖ " + problem)
                result_lbl.configure(bootstyle="danger")
                return
            result.set("Sprawdzam...")
            result_lbl.configure(bootstyle="secondary")
            btn_test.state(["disabled"])

            def work():
                try:
                    ip = test_proxy(p)
                    msg, style = f"✔ Działa. IP widoczne w sieci: {ip}", "success"
                except Exception as err:
                    msg, style = f"✖ Nie działa: {err}", "danger"

                def show():
                    if win.winfo_exists():
                        result.set(msg)
                        result_lbl.configure(bootstyle=style)
                        btn_test.state(["!disabled"])
                self.root.after(0, show)
            threading.Thread(target=work, daemon=True).start()

        btn_test = tb.Button(test_row, text="Sprawdź proxy", bootstyle="info outline", command=run_test)
        btn_test.pack(side="left")
        result_lbl.pack(side="left", padx=12)

        # --- browser
        bf = tb.Labelframe(body, text="  Przeglądarka  ", padding=16, bootstyle="info")
        bf.pack(fill="x", pady=(14, 0))
        v_show_browser = tk.BooleanVar(value=not self.settings.get("headless", True))
        tb.Checkbutton(bf, text="Pokazuj okno przeglądarki (do diagnostyki)", variable=v_show_browser,
                       bootstyle="toggle").pack(anchor="w")

        # --- buttons
        btns = tb.Frame(body)
        btns.pack(fill="x", pady=(16, 0))

        def save_and_close():
            p = collect()
            problem = validate(p)
            if problem:
                result.set("✖ " + problem)
                result_lbl.configure(bootstyle="danger")
                return
            old = (self.settings.get("proxy"), self.settings.get("headless"))
            self.settings["proxy"] = p
            self.settings["headless"] = not v_show_browser.get()
            save_settings(self.settings)
            self._update_proxy_label()
            win.destroy()
            if old != (self.settings["proxy"], self.settings["headless"]):
                note = "\n\nTrwające wysyłanie zostanie zatrzymane." if self.sending else ""
                if self.ask("Ustawienia", "Uruchomić przeglądarkę ponownie, aby zastosować zmiany?" + note):
                    self.logged_in = False
                    self.worker.send("stop_sending")
                    self.worker.send("start")

        tb.Button(btns, text="Zapisz", bootstyle="primary", command=save_and_close, width=12).pack(side="right")
        tb.Button(btns, text="Anuluj", bootstyle="secondary outline", command=win.destroy,
                  width=10).pack(side="right", padx=8)
        win.bind("<Escape>", lambda e: win.destroy())
        win.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - win.winfo_width()) // 2
        y = self.root.winfo_rooty() + 60
        win.geometry(f"+{x}+{y}")
        win.grab_set()

    def logout(self):
        if self.ask(
            "Wyloguj",
            "Usunąć zapisaną sesję z tego komputera? Trzeba będzie zalogować się ponownie.\n\n"
            "Aby całkiem zakończyć sesję, usuń też urządzenie w Telegramie:\n"
            "Ustawienia \u203a Urządzenia.",
        ):
            self.logged_in = False
            self.worker.send("logout")

    def open_data_dir(self):
        path = str(app_data_dir())
        try:
            if os.name == "nt":
                os.startfile(path)
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception:
            self.info("Folder danych", path)

    def about(self):
        self.info(
            "O programie",
            f"Telegram AutoMessage {APP_VERSION}\n\nWysyła wiadomość lub przekazuje wybraną wiadomość do grup, kanałów "
            "i tematów forum przez Telegram Web, w tle.\n\nDane i sesja:\n" + str(app_data_dir()))

    def on_close(self):
        if self.sending and not self.ask("Zakończ", "Wysyłanie trwa. Zatrzymać i zamknąć?"):
            return
        try:
            self._collect_settings()
            save_settings(self.settings)
        except Exception:
            pass
        self.worker.send("shutdown")
        self._set_status("Zamykanie...", "secondary")
        self.root.after(5000, self.root.destroy)  # safety net if the browser hangs

    # ---------------------------------------------------------------- worker events
    def _log(self, text, replace=False):
        self.log_text.configure(state="normal")
        if replace and self._replace_line:
            self.log_text.delete("end-2l", "end-1l")
        stamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.insert("end", f"{stamp}  {text}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")
        self._replace_line = replace
        if text.startswith("Wyslano do:"):
            self.toast("Wysłano", text.split(":", 1)[1].strip(), "success")
        elif text.startswith("Blad wysylki"):
            self.toast("Błąd wysyłki", text, "danger")

    def _on_login_state(self, state, error):
        self.login_error.set(error or "")
        was_logged_in = self.logged_in
        self.logged_in = state == "logged_in"
        if self.logged_in:
            self._hide_login()
            self._set_status("\u25cf  Zalogowano", "success")
            if not was_logged_in:
                self.toast("Telegram", "Zalogowano pomyślnie.", "success")
                self.scan()
        elif state in ("phone", "qr"):
            self.login_hint.set("Podaj numer telefonu z kierunkowym, np. +48 600 100 200.\n"
                                "Kod logowania przyjdzie w aplikacji Telegram.")
            self._set_status("\u25cf  Niezalogowany", "warning")
            self._show_login("phone")
        elif state == "code":
            self.code_var.set("")
            self.login_hint.set("Wpisz kod, który Telegram wysłał do aplikacji (albo SMS-em).")
            self._set_status("\u25cf  Czekam na kod", "warning")
            self._show_login("code")
        elif state == "password":
            self.login_hint.set("Konto ma weryfikację dwuetapową. Wpisz hasło chmury Telegram.")
            self._set_status("\u25cf  Czekam na hasło 2FA", "warning")
            self._show_login("password")
        elif state == "signup":
            self.login_error.set("Ten numer nie ma konta Telegram. Załóż je najpierw w aplikacji.")
            self._show_login("phone")
        else:
            self._set_status("\u25cf  Brak połączenia", "danger")
            self._log("Telegram Web nie odpowiada. Spróbuj: Konto \u203a Połącz ponownie.")
        self._update_controls()

    def _idle_status(self):
        if self.sending:
            self._set_status("\u25cf  Wysyłanie aktywne", "success")
        elif self.logged_in:
            self._set_status("\u25cf  Zalogowano", "success")

    def _poll_events(self):
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "log":
                    self._log(payload)
                elif kind == "log_replace":
                    self._log(payload, replace=True)
                elif kind == "busy":
                    self.busy, text = payload
                    if self.busy:
                        self._show_busy(text)
                    else:
                        self._hide_busy()
                        self._idle_status()
                    self._update_controls()
                elif kind == "login_state":
                    self._on_login_state(*payload)
                elif kind == "scan":
                    self.scan_data = payload
                    self._rebuild_targets()
                    self._collect_settings()
                    save_settings(self.settings)
                    self._refresh_tree()
                    self._refresh_sources()
                    self.toast("Skanowanie zakończone", f"{len(self._targets)} miejsc do pisania.", "info")
                elif kind == "history":
                    self._show_history(payload)
                elif kind == "ip":
                    self._update_proxy_label(payload)
                    if payload is None and proxy_url(self.settings.get("proxy")):
                        self.toast("Proxy", "Nie udało się połączyć przez proxy. Sprawdź ustawienia.", "danger")
                elif kind == "sending":
                    self.sending = payload
                    self._idle_status()
                    self._update_controls()
                    self._update_summary()
                elif kind == "schedule":
                    self.schedule = {s["key"]: s for s in payload}
                    self._update_schedule_cells()
                elif kind == "closed":
                    self.root.destroy()
                    return
        except queue.Empty:
            pass
        self.root.after(150, self._poll_events)

    def _update_controls(self):
        ready = self.logged_in and not self.busy
        self.btn_scan.state(["!disabled"] if ready and not self.sending else ["disabled"])
        self.btn_start.state(["!disabled"] if ready and not self.sending else ["disabled"])
        self.btn_stop.state(["!disabled"] if self.sending else ["disabled"])
        self.btn_now.state(["!disabled"] if self.sending and not self.busy else ["disabled"])
        self.btn_test.state(["!disabled"] if ready else ["disabled"])
        self.btn_load.state(["!disabled"] if ready else ["disabled"])
        for _, _, ent, btn in self.login_rows.values():
            ent.state(["disabled"] if self.busy else ["!disabled"])
            btn.state(["disabled"] if self.busy else ["!disabled"])


def run():
    settings = load_settings()
    root = tb.Window(title="Telegram AutoMessage", themename=settings.get("theme", DEFAULT_THEME),
                     size=(1040, 760), minsize=(800, 600), iconphoto=str(ASSETS_DIR / "icon-256.png"))
    # note: an extra iconbitmap(default=.ico) here resets the title bar to a generic icon on Windows
    App(root)
    root.place_window_center()
    root.mainloop()
