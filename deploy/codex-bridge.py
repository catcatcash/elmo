#!/usr/bin/env python3
"""Local bridge so the Elmo worker can call the host Codex CLI."""

import json
import os
import subprocess
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

TOKEN = os.environ["CODEX_BRIDGE_TOKEN"]
HOST = os.environ.get("CODEX_BRIDGE_HOST", "172.18.0.1")
PORT = int(os.environ.get("CODEX_BRIDGE_PORT", "8765"))
WORKDIR = os.environ.get("CODEX_BRIDGE_WORKDIR", "/home/babysor00/elmo/codex-work")


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/health":
            self.send_error(404)
            return
        body = b'{"ok":true}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path != "/run":
            self.send_error(404)
            return
        if self.headers.get("Authorization") != f"Bearer {TOKEN}":
            self.send_error(401)
            return
        length = int(self.headers.get("Content-Length", "0"))
        try:
            payload = json.loads(self.rfile.read(length))
        except json.JSONDecodeError:
            self.send_error(400)
            return
        prompt = payload.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            self._json(400, {"ok": False, "error": "prompt is required"})
            return
        schema = payload.get("schema")
        model = payload.get("model") if isinstance(payload.get("model"), str) else None
        try:
            text, code = self._run(prompt, schema if isinstance(schema, dict) else None, model)
        except subprocess.TimeoutExpired:
            self._json(200, {"ok": False, "error": "codex timed out"})
            return
        except Exception:
            self._json(200, {"ok": False, "error": "codex bridge failed"})
            return
        if code != 0 or not text.strip():
            self._json(200, {"ok": False, "error": f"codex exit {code}"})
            return
        self._json(200, {"ok": True, "text": text})

    def _run(self, prompt: str, schema: dict | None, model: str | None) -> tuple[str, int]:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "last.txt"
            chosen = (model or os.environ.get("CODEX_MODEL") or "").strip()
            effort = (os.environ.get("CODEX_REASONING_EFFORT") or "").strip()
            cmd = [
                "codex",
                "exec",
                "--ephemeral",
                "--skip-git-repo-check",
                "--sandbox",
                "read-only",
                "--color",
                "never",
                "--ignore-user-config",
                "--ignore-rules",
                "-C",
                WORKDIR,
                "-o",
                str(out),
            ]
            if chosen:
                cmd.extend(["-m", chosen])
            if effort:
                cmd.extend(["-c", f'model_reasoning_effort="{effort}"'])
            if schema is not None:
                schema_path = Path(tmp) / "schema.json"
                schema_path.write_text(json.dumps(schema))
                cmd.extend(["--output-schema", str(schema_path)])
            cmd.append("-")
            result = subprocess.run(
                cmd,
                input=prompt,
                text=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=300,
                check=False,
            )
            text = out.read_text() if out.exists() else ""
            return text, result.returncode

    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args) -> None:
        print(f"codex-bridge {self.command} {self.path}", flush=True)


def main() -> None:
    Path(WORKDIR).mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"codex-bridge listening on {HOST}:{PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
