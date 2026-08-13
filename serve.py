#!/usr/bin/env python3
"""torrest-web server: serves the built app (build/) and proxies the Torrest
API on the same origin, so the browser hits no CORS wall and the app needs no
Base URL configuration (empty base URL = same origin).

Configuration lives in ~/.config/torrest-web/config (auto-created with
defaults on first run): ENGINE_HOST/ENGINE_PORT say where the Torrest
engine runs, LISTEN_PORT where this server listens.

Usage: serve.py [port]     (overrides LISTEN_PORT; binds 127.0.0.1 only)
"""
import http.server
import re
import shutil
import sys
import urllib.error
import urllib.request
from functools import partial
from pathlib import Path

API_PREFIXES = ("/torrents", "/add/", "/pause", "/resume", "/status",
                "/shutdown", "/settings")
FWD_REQ_HEADERS = ("Content-Type", "Range", "If-Modified-Since",
                   "Cache-Control")
FWD_RESP_HEADERS = ("Content-Type", "Content-Length", "Content-Range",
                    "Accept-Ranges")
CONFIG_FILE = Path.home() / ".config/torrest-web/config"
CONFIG_TEMPLATE = """\
# torrest-web configuration
#
# ENGINE_HOST/ENGINE_PORT: where the Torrest engine runs. mDNS names
# (host.local) survive DHCP/IP changes; a plain IP works too.
ENGINE_HOST="localhost"
ENGINE_PORT="61235"
# LISTEN_PORT: local port where this panel is served.
LISTEN_PORT="8135"
"""


def load_config():
    if not CONFIG_FILE.exists():
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(CONFIG_TEMPLATE)
        print("Created default config: {}".format(CONFIG_FILE))
    conf = {}
    for line in CONFIG_FILE.read_text().splitlines():
        m = re.match(r'^\s*(\w+)\s*=\s*"?([^"#]+?)"?\s*$', line)
        if m:
            conf[m.group(1)] = m.group(2).strip()
    return conf


CONFIG = load_config()
ENGINE = "http://{}:{}".format(CONFIG.get("ENGINE_HOST", "localhost"),
                               CONFIG.get("ENGINE_PORT", "61235"))


class Handler(http.server.SimpleHTTPRequestHandler):

    def log_message(self, fmt, *args):
        pass

    def _is_api(self):
        return self.path.startswith(API_PREFIXES)

    def _proxy(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else None
        req = urllib.request.Request(ENGINE + self.path, data=body,
                                     method=self.command)
        for header in FWD_REQ_HEADERS:
            value = self.headers.get(header)
            if value:
                req.add_header(header, value)

        try:
            resp = urllib.request.urlopen(req, timeout=3600)
        except urllib.error.HTTPError as e:
            resp = e
        except Exception as e:
            msg = "cannot reach Torrest engine at {}: {}".format(
                ENGINE, e).encode()
            self.send_response(502)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(msg)))
            self.end_headers()
            self.wfile.write(msg)
            return

        try:
            self.send_response(getattr(resp, "status", None) or resp.code)
            for header in FWD_RESP_HEADERS:
                value = resp.headers.get(header)
                if value:
                    self.send_header(header, value)
            self.end_headers()
            # Stream in chunks: file serving (video) must not buffer in RAM.
            shutil.copyfileobj(resp, self.wfile, 64 * 1024)
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            resp.close()

    def do_GET(self):
        if self._is_api():
            self._proxy()
        else:
            super().do_GET()

    def do_POST(self):
        if self._is_api():
            self._proxy()
        else:
            self.send_error(404)

    def do_PUT(self):
        if self._is_api():
            self._proxy()
        else:
            self.send_error(404)

    def do_DELETE(self):
        if self._is_api():
            self._proxy()
        else:
            self.send_error(404)


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else int(
        CONFIG.get("LISTEN_PORT", "8135"))
    build = Path(__file__).resolve().parent / "build"
    if not (build / "index.html").exists():
        sys.exit("no build/ found next to serve.py — run 'npm run build' "
                 "or deploy the built app first")
    handler = partial(Handler, directory=str(build))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    print("torrest-web: serving {} on http://127.0.0.1:{} -> engine {}".format(
        build, port, ENGINE))
    server.serve_forever()


if __name__ == "__main__":
    main()
