#!/usr/bin/env python3
"""Serve the Stratzy credit spread report on localhost."""
import http.server
import os
import socketserver
from pathlib import Path

PORT = 8765
DIR = Path(__file__).parent


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DIR), **kwargs)


if __name__ == '__main__':
    os.chdir(DIR)
    with socketserver.TCPServer(('', PORT), Handler) as httpd:
        print(f'Stratzy Credit Spread Report → http://localhost:{PORT}')
        print('Press Ctrl+C to stop')
        httpd.serve_forever()