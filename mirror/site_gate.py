#!/usr/bin/env python3
"""Tiny static server for the --local mirror only (the real box uses the
front-door web server). Serves the site dir on 127.0.0.1.

Routes: / -> index.html, /node -> node.html,
/v1/tokyo-pass -> tokyo-pass.json, anything else -> the file in the
site dir, else 404. Stdlib only.

Usage: site_gate.py <port> <site-dir>
"""
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(sys.argv[1])
ROOT = os.path.abspath(sys.argv[2])
ROUTES = {"/": "index.html", "/node": "node.html",
          "/v1/tokyo-pass": "tokyo-pass.json"}
TYPES = {".html": "text/html; charset=utf-8",
         ".json": "application/json",
         ".txt": "text/plain; charset=utf-8",
         ".css": "text/css",
         ".js": "application/javascript"}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split("?", 1)[0]
        name = ROUTES.get(path) or path.lstrip("/")
        fpath = os.path.join(ROOT, name)
        if os.path.isdir(fpath):
            fpath = os.path.join(fpath, "index.html")
        if (not os.path.isfile(fpath)
                or not os.path.abspath(fpath).startswith(ROOT)):
            return self.send_error(404)
        data = open(fpath, "rb").read()
        self.send_response(200)
        self.send_header("Content-Type",
                         TYPES.get(os.path.splitext(fpath)[1],
                                   "application/octet-stream"))
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
