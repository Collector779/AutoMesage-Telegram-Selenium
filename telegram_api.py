"""Talk to Telegram Web K through its own in-page managers (appImManager.managers).

Everything runs inside the logged-in page, so nothing is clicked, no chat is opened
and nothing gets marked as read. Each helper is an async JS snippet run via Selenium.
"""

_PRELUDE = r"""
const done = arguments[arguments.length - 1];
const args = arguments;
const fail = e => done({error: String(e && (e.type || e.message || e.description) || e)});
if (!window.appImManager || !window.appImManager.managers) { done({error: 'Telegram Web nie jest gotowy (brak managers)'}); return; }
const m = window.appImManager.managers;
const userName = u => [u.first_name, u.last_name].filter(Boolean).join(' ') || (u.username ? '@' + u.username : String(u.id));
async function allDialogs(filterId) {
  let limit = 100, r;
  for (let i = 0; i < 20; i++) {
    r = await m.dialogsStorage.getDialogs({filterId, limit});
    if (r.isEnd || r.dialogs.length < limit) break;
    limit += 200;
  }
  return r.dialogs;
}
"""

_SCAN_JS = _PRELUDE + r"""
(async () => {
  const myId = window.rootScope.myId;
  const seen = new Set();
  const groups = [], privates = [];
  for (const [filterId, archived] of [[0, false], [1, true]]) {
    let dialogs = [];
    try { dialogs = await allDialogs(filterId); } catch (e) { if (filterId === 0) throw e; }
    for (const d of dialogs) {
      const peerId = d.peerId;
      if (seen.has(peerId)) continue; seen.add(peerId);
      if (peerId > 0) {
        const u = await m.appUsersManager.getUser(peerId);
        if (!u || u._ !== 'user') continue;
        privates.push({peer_id: String(peerId), name: peerId === myId ? 'Zapisane wiadomości' : userName(u),
                       bot: !!u.pFlags?.bot, archived});
        continue;
      }
      const chatId = -peerId;
      const c = await m.appChatsManager.getChat(chatId);
      if (!c || (c._ !== 'channel' && c._ !== 'chat')) continue;  // chatForbidden / channelForbidden
      if (c.pFlags?.left || c.pFlags?.deactivated) continue;
      const kind = c.pFlags?.broadcast ? 'channel' : (c.pFlags?.forum ? 'forum' : 'group');
      let canSend = false, reason = '';
      try { canSend = !!(await m.appChatsManager.hasRights(chatId, 'send_plain')); } catch (e) { reason = 'blad sprawdzania praw'; }
      if (!canSend && !reason) reason = kind === 'channel' ? 'kanał – piszą tylko admini' : 'pisanie wyłączone przez adminów';
      const g = {peer_id: String(peerId), name: c.title || String(peerId), kind, archived,
                 can_send: canSend, reason, slowmode: c.slowmode_seconds || 0, topics: []};
      if (kind === 'forum') {
        let topics = [];
        try { topics = await allDialogs(peerId); } catch (e) { g.reason = 'nie udało się pobrać tematów'; }
        for (const t of topics) {
          if (t._ !== 'forumTopic') continue;
          let ok = canSend, why = canSend ? '' : g.reason;
          if (ok && t.pFlags?.closed) {
            let manage = false;
            try { manage = !!(await m.dialogsStorage.canManageTopic(t)); } catch (e) {}
            if (!manage) { ok = false; why = 'temat zamknięty'; }
          }
          if (ok && t.pFlags?.hidden) { /* hidden General topic still accepts messages */ }
          g.topics.push({thread_id: String(t.id), name: t.title || ('#' + t.id), can_send: ok, reason: why,
                         closed: !!t.pFlags?.closed});
        }
      }
      groups.push(g);
    }
  }
  done({groups, privates, my_id: String(myId)});
})().catch(fail);
"""

_HISTORY_JS = _PRELUDE + r"""
(async () => {
  const peerId = +args[0], limit = args[1] || 30;
  const r = await m.appMessagesManager.getHistory({peerId, limit, fetchIfWasNotFetched: true});
  const mids = (r.history || []).slice(0, limit);
  const out = [];
  for (const mid of mids) {
    const msg = await m.appMessagesManager.getMessageByPeer(peerId, mid);
    if (!msg || msg._ !== 'message') continue;
    let media = '';
    if (msg.media) {
      const t = msg.media._ || '';
      media = t.includes('Photo') ? 'zdjęcie' : t.includes('Document') ? (msg.media.document?.type === 'video' ? 'wideo' : msg.media.document?.type === 'gif' ? 'GIF' : msg.media.document?.sticker ? 'naklejka' : 'plik')
            : t.includes('WebPage') ? '' : t.includes('Poll') ? 'ankieta' : t.includes('Geo') ? 'lokalizacja' : t.includes('Contact') ? 'kontakt' : 'media';
    }
    out.push({mid: String(mid), date: msg.date, out: !!msg.pFlags?.out, text: (msg.message || '').slice(0, 300), media,
              noforwards: !!msg.pFlags?.noforwards});
  }
  done({messages: out});
})().catch(fail);
"""

# Send / forward. Rejections and `message_error` events both count as failures.
_SEND_JS = _PRELUDE + r"""
(async () => {
  const [mode, peerIdS, threadIdS, payload] = [args[0], args[1], args[2], args[3]];
  const peerId = +peerIdS, threadId = threadIdS ? +threadIdS : undefined;
  const errors = [];
  const onErr = e => { if (e && e.peerId === peerId) errors.push(e.error && (e.error.type || e.error.message) || 'blad wysylki'); };
  const rs = window.rootScope;
  rs.addEventListener('message_error', onErr);
  try {
    if (mode === 'forward') {
      const fromPeerId = +payload.from_peer_id, mid = +payload.mid;
      let src = await m.appMessagesManager.getMessageByPeer(fromPeerId, mid);
      if (!src) { await m.appMessagesManager.reloadMessages(fromPeerId, [mid]); src = await m.appMessagesManager.getMessageByPeer(fromPeerId, mid); }
      if (!src || src._ !== 'message') throw 'wiadomość źródłowa nie istnieje (usunięta?)';
      await m.appMessagesManager.forwardMessages({peerId, fromPeerId, mids: [mid], threadId,
                                                  dropAuthor: !!payload.drop_author});
    } else {
      await m.appMessagesManager.sendText({peerId, threadId, text: payload.text});
    }
    await new Promise(r => setTimeout(r, 4000));
  } catch (e) {
    errors.push(String(e && (e.type || e.message) || e));
  } finally {
    rs.removeEventListener('message_error', onErr);
  }
  done(errors.length ? {error: errors.join('; ')} : {ok: true});
})().catch(fail);
"""


class TelegramApiError(RuntimeError):
    pass


def _run(driver, js, *args, timeout=180):
    driver.set_script_timeout(timeout)
    res = driver.execute_async_script(js, *args)
    if isinstance(res, dict) and res.get("error"):
        raise TelegramApiError(res["error"])
    return res


def scan(driver):
    """Return {'groups': [...], 'privates': [...], 'my_id': str} straight from Telegram's own state."""
    return _run(driver, _SCAN_JS, timeout=300)


def history(driver, peer_id, limit=30):
    return _run(driver, _HISTORY_JS, str(peer_id), int(limit))["messages"]


def send_text(driver, peer_id, thread_id, text):
    _run(driver, _SEND_JS, "text", str(peer_id), str(thread_id or ""), {"text": text}, timeout=60)


def forward(driver, peer_id, thread_id, from_peer_id, mid, drop_author=False):
    _run(driver, _SEND_JS, "forward", str(peer_id), str(thread_id or ""),
         {"from_peer_id": str(from_peer_id), "mid": str(mid), "drop_author": bool(drop_author)}, timeout=60)
