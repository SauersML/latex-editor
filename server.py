#!/usr/bin/env python3
"""
Local LaTeX editor server.

- Saves homework.tex to disk on every edit
- Compiles to PDF via tectonic (offline)
- Auto-commits to git for version history
- No external API calls after initial tectonic package download

Usage:  python3 server.py
        Then open http://localhost:8462
"""

import http.server
import json
import subprocess
import urllib.parse
from datetime import datetime
from pathlib import Path

PORT = 8462
PROJECT_DIR = Path(__file__).parent.resolve()
TEX_FILE = PROJECT_DIR / "homework.tex"
PDF_FILE = PROJECT_DIR / "homework.pdf"


def git(*args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(PROJECT_DIR), *args],
        capture_output=True, text=True, timeout=5,
    )
    return result.stdout.strip()


def compile_tex() -> str | None:
    """Compile homework.tex to PDF. Returns error string or None on success."""
    result = subprocess.run(
        ["tectonic", "-X", "compile", str(TEX_FILE)],
        capture_output=True, text=True, timeout=30,
        cwd=str(PROJECT_DIR),
    )
    if result.returncode != 0:
        return result.stderr.strip() or result.stdout.strip() or "Unknown compile error"
    return None


def git_save(content: str) -> dict:
    """Write content to disk, compile, and commit if changed."""
    TEX_FILE.write_text(content, encoding="utf-8")

    # Compile
    compile_error = compile_tex()

    # Stage and check for changes
    git("add", str(TEX_FILE))
    status = git("status", "--porcelain", str(TEX_FILE))

    committed = False
    if status:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        git("commit", "-m", f"Auto-save {timestamp}")
        committed = True

    result = {"saved": True, "committed": committed}
    if compile_error:
        result["compile_error"] = compile_error
    return result


def git_log() -> list[dict]:
    raw = git("log", "--pretty=format:%H\t%h\t%s\t%ci", "--follow", "--", str(TEX_FILE))
    if not raw:
        return []
    commits = []
    for line in raw.splitlines():
        full_hash, short_hash, message, date = line.split("\t", 3)
        commits.append({"hash": full_hash, "short": short_hash, "message": message, "date": date})
    return commits


def git_show(commit_hash: str) -> str:
    if not all(c in "0123456789abcdef" for c in commit_hash.lower()):
        return ""
    return git("show", f"{commit_hash}:{TEX_FILE.name}")


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        if "/save" in str(args):
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Saved + compiled")

    def send_json(self, data: dict, status: int = 200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path

        if path == "/" or path == "/index.html":
            self._serve_file(PROJECT_DIR / "editor.html", "text/html")
        elif path == "/load":
            content = TEX_FILE.read_text(encoding="utf-8") if TEX_FILE.exists() else ""
            self.send_json({"content": content})
        elif path == "/pdf":
            if PDF_FILE.exists():
                self._serve_file(PDF_FILE, "application/pdf")
            else:
                self.send_response(404)
                self.end_headers()
        elif path == "/versions":
            self.send_json({"commits": git_log()})
        elif path.startswith("/version/"):
            commit_hash = path.split("/version/", 1)[1]
            self.send_json({"content": git_show(commit_hash)})
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path

        if path == "/save":
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))
            result = git_save(body["content"])
            self.send_json(result)
        elif path == "/restore":
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))
            content = git_show(body["hash"])
            if content:
                result = git_save(content)
                result["content"] = content
                self.send_json(result)
            else:
                self.send_json({"error": "Version not found"}, 404)
        else:
            self.send_response(404)
            self.end_headers()

    def _serve_file(self, filepath: Path, content_type: str):
        if not filepath.exists():
            self.send_response(404)
            self.end_headers()
            return
        data = filepath.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)


def main():
    server = http.server.HTTPServer(("127.0.0.1", PORT), Handler)
    print(f"LaTeX editor running at http://localhost:{PORT}")
    print(f"Editing: {TEX_FILE}")
    print(f"Compiler: tectonic (offline)")
    print("Press Ctrl+C to stop.\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        server.server_close()


if __name__ == "__main__":
    main()
