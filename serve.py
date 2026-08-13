#!/usr/bin/env python3
"""torrest-web server: serves the built app (build/) and proxies the Torrest
API on the same origin, so the browser hits no CORS wall and the app needs no
Base URL configuration (empty base URL = same origin).

The Torrest engine location is read from ~/.config/torrestctl/config
(HOST/PORT — shared with the torrestctl CLI); defaults to localhost:61235.

Usage: serve.py [port]     (default 8135; binds 127.0.0.1 only)
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
DEFAULT_PORT = 8135


def engine_base():
    conf = {}
    cfg = Path.home() / ".config/torrestctl/config"
    if cfg.exists():
        for line in cfg.read_text().splitlines():
            m = re.match(r'^\s*(HOST|PORT)\s*=\s*"?([^"#]+?)"?\s*$', line)
            if m:
                conf[m.group(1)] = m.group(2).strip()
    return "http://{}:{}".format(conf.get("HOST", "localhost"),
                                 conf.get("PORT", "61235"))


ENGINE = engine_base()


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
    port = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PORT
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
