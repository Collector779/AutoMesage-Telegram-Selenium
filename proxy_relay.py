"""Local proxy relay: Chrome talks to 127.0.0.1 without a password, the relay logs in upstream.

Chrome cannot send proxy credentials from background workers (where Telegram Web keeps its
connections) and does not support SOCKS5 login at all. This relay accepts plain HTTP proxy
requests from Chrome and forwards them through the user's HTTP/HTTPS/SOCKS5/SOCKS4 proxy
with the configured login. Standard library only.
"""
import base64
import ipaddress
import select
import socket
import socketserver
import ssl
import struct
import threading
from urllib.parse import urlsplit


class UpstreamError(OSError):
    pass


def _recv_exact(sock, n):
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise UpstreamError("proxy zamknął połączenie")
        buf += chunk
    return buf


def _read_http_head(sock):
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = sock.recv(4096)
        if not chunk:
            raise UpstreamError("proxy zamknął połączenie")
        data += chunk
        if len(data) > 65536:
            raise UpstreamError("zbyt długa odpowiedź proxy")
    head, rest = data.split(b"\r\n\r\n", 1)
    return head.decode("latin1"), rest


def open_tunnel(proxy, host, port, timeout=20):
    """Return a socket connected to host:port through the configured upstream proxy."""
    ptype = proxy.get("type", "http").lower()
    phost, pport = str(proxy["host"]).strip(), int(str(proxy["port"]).strip())
    user, pwd = str(proxy.get("username", "")).strip(), str(proxy.get("password", ""))
    s = socket.create_connection((phost, pport), timeout=timeout)
    try:
        if ptype == "https":
            s = ssl.create_default_context().wrap_socket(s, server_hostname=phost)
        if ptype in ("http", "https"):
            req = f"CONNECT {host}:{port} HTTP/1.1\r\nHost: {host}:{port}\r\n"
            if user:
                token = base64.b64encode(f"{user}:{pwd}".encode()).decode()
                req += f"Proxy-Authorization: Basic {token}\r\n"
            s.sendall((req + "\r\n").encode())
            head, rest = _read_http_head(s)
            status = head.split("\r\n", 1)[0]
            code = status.split(" ")[1] if " " in status else "?"
            if code == "407":
                raise UpstreamError("proxy odrzuciło login lub hasło (407)")
            if code != "200":
                raise UpstreamError(f"proxy odpowiedziało: {status}")
            if rest:
                raise UpstreamError("nieoczekiwane dane od proxy")
        elif ptype == "socks5":
            methods = b"\x00\x02" if user else b"\x00"
            s.sendall(b"\x05" + bytes([len(methods)]) + methods)
            ver, method = _recv_exact(s, 2)
            if ver != 5:
                raise UpstreamError("to nie jest proxy SOCKS5")
            if method == 2:
                u, p = user.encode(), pwd.encode()
                s.sendall(b"\x01" + bytes([len(u)]) + u + bytes([len(p)]) + p)
                if _recv_exact(s, 2)[1] != 0:
                    raise UpstreamError("proxy SOCKS5 odrzuciło login lub hasło")
            elif method != 0:
                raise UpstreamError("proxy SOCKS5 wymaga logowania" if not user else "proxy SOCKS5 odmówiło")
            try:
                addr = b"\x01" + ipaddress.IPv4Address(host).packed
            except ValueError:
                h = host.encode("idna")
                addr = b"\x03" + bytes([len(h)]) + h
            s.sendall(b"\x05\x01\x00" + addr + struct.pack(">H", port))
            ver, rep, _, atyp = _recv_exact(s, 4)
            if rep != 0:
                raise UpstreamError(f"proxy SOCKS5 nie połączyło z {host} (kod {rep})")
            _recv_exact(s, {1: 4, 4: 16}.get(atyp, 0) or _recv_exact(s, 1)[0])
            _recv_exact(s, 2)
        elif ptype == "socks4":
            ip = socket.gethostbyname(host)
            s.sendall(b"\x04\x01" + struct.pack(">H", port) + socket.inet_aton(ip) + user.encode() + b"\x00")
            if _recv_exact(s, 8)[1] != 0x5A:
                raise UpstreamError(f"proxy SOCKS4 nie połączyło z {host}")
        else:
            raise UpstreamError(f"nieznany typ proxy: {ptype}")
        s.settimeout(None)
        return s
    except Exception:
        s.close()
        raise


def _pipe(a, b):
    socks = [a, b]
    try:
        while True:
            r, _, _ = select.select(socks, [], [], 300)
            if not r:
                return
            for s in r:
                data = s.recv(65536)
                if not data:
                    return
                (b if s is a else a).sendall(data)
    except OSError:
        pass


class _Handler(socketserver.BaseRequestHandler):
    def handle(self):
        client = self.request
        relay = self.server.relay
        try:
            head, rest = _read_http_head(client)
        except OSError:
            return
        lines = head.split("\r\n")
        try:
            method, target, version = lines[0].split(" ", 2)
        except ValueError:
            return
        try:
            if method.upper() == "CONNECT":
                host, port = target.rsplit(":", 1)
                upstream = open_tunnel(relay.proxy, host.strip("[]"), int(port))
                client.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                if rest:
                    upstream.sendall(rest)
            else:
                # plain http:// request: rewrite to origin-form and send through a tunnel
                url = urlsplit(target)
                if url.scheme != "http" or not url.hostname:
                    client.sendall(b"HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\n\r\n")
                    return
                upstream = open_tunnel(relay.proxy, url.hostname, url.port or 80)
                path = (url.path or "/") + (f"?{url.query}" if url.query else "")
                kept = [l for l in lines[1:] if not l.lower().startswith(("proxy-", "connection:"))]
                req = "\r\n".join([f"{method} {path} {version}", *kept, "Connection: close", "", ""])
                upstream.sendall(req.encode("latin1") + rest)
        except Exception as err:
            relay.last_error = str(err)
            msg = str(err).encode("utf-8", "replace")
            try:
                client.sendall(b"HTTP/1.1 502 Bad Gateway\r\nContent-Type: text/plain; charset=utf-8\r\n"
                               b"Content-Length: " + str(len(msg)).encode() + b"\r\n\r\n" + msg)
            except OSError:
                pass
            return
        try:
            _pipe(client, upstream)
        finally:
            upstream.close()


class _Server(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True


class ProxyRelay:
    """Start with ProxyRelay(proxy_cfg).start(); Chrome then uses http://127.0.0.1:<port>."""

    def __init__(self, proxy):
        self.proxy = dict(proxy)
        self.last_error = ""
        self._server = None

    def start(self):
        self._server = _Server(("127.0.0.1", 0), _Handler)
        self._server.relay = self
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        return self

    @property
    def url(self):
        return f"http://127.0.0.1:{self._server.server_address[1]}"

    def stop(self):
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._server = None


def test_proxy(proxy, host="api.ipify.org", timeout=15):
    """Connect through the proxy and return the public IP seen by the outside world."""
    s = open_tunnel(proxy, host, 443, timeout=timeout)
    try:
        s = ssl.create_default_context().wrap_socket(s, server_hostname=host)
        s.settimeout(timeout)
        s.sendall(f"GET / HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n\r\n".encode())
        data = b""
        while True:
            chunk = s.recv(4096)
            if not chunk:
                break
            data += chunk
        head, _, body = data.partition(b"\r\n\r\n")
        if b" 200 " not in head.split(b"\r\n", 1)[0]:
            raise UpstreamError("nie udało się pobrać IP przez proxy")
        return body.decode().strip()
    finally:
        s.close()
