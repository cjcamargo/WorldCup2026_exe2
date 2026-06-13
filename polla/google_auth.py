from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any


class GoogleAuthError(RuntimeError):
    pass


def load_oauth_client(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise GoogleAuthError(f"No existe el archivo de credenciales OAuth: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    client = payload.get("installed") or payload.get("web") or payload
    if not client.get("client_id") or not client.get("client_secret"):
        raise GoogleAuthError("El archivo OAuth debe incluir client_id y client_secret.")
    return client


def token_is_valid(token: dict[str, Any]) -> bool:
    return bool(token.get("access_token")) and int(token.get("expires_at", 0)) > int(time.time()) + 60


def load_token(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def save_token(path: Path, token: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(token, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def get_access_token(credentials_path: Path, token_path: Path, scopes: list[str]) -> str:
    token = load_token(token_path)
    if token and token_is_valid(token):
        return token["access_token"]
    client = load_oauth_client(credentials_path)
    if token and token.get("refresh_token"):
        refreshed = refresh_access_token(client, token)
        save_token(token_path, refreshed)
        return refreshed["access_token"]
    raise GoogleAuthError(
        "No hay token de Google Drive. Ejecuta scripts\\auth_google_drive.py una vez."
    )


def refresh_access_token(client: dict[str, Any], token: dict[str, Any]) -> dict[str, Any]:
    token_uri = client.get("token_uri", "https://oauth2.googleapis.com/token")
    body = urllib.parse.urlencode({
        "client_id": client["client_id"],
        "client_secret": client["client_secret"],
        "refresh_token": token["refresh_token"],
        "grant_type": "refresh_token",
    }).encode("utf-8")
    data = _post_json(token_uri, body)
    merged = dict(token)
    merged.update(data)
    merged["expires_at"] = int(time.time()) + int(data.get("expires_in", 3600))
    return merged


def run_local_oauth(credentials_path: Path, token_path: Path, scopes: list[str]) -> Path:
    client = load_oauth_client(credentials_path)
    auth_uri = client.get("auth_uri", "https://accounts.google.com/o/oauth2/v2/auth")
    token_uri = client.get("token_uri", "https://oauth2.googleapis.com/token")
    server = _OAuthCallbackServer(("127.0.0.1", 0), _OAuthCallbackHandler)
    redirect_uri = f"http://127.0.0.1:{server.server_port}/callback"
    query = urllib.parse.urlencode({
        "client_id": client["client_id"],
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(scopes),
        "access_type": "offline",
        "prompt": "consent",
    })
    auth_url = f"{auth_uri}?{query}"
    print("Abre esta URL para autorizar Google Drive:")
    print(auth_url)
    try:
        webbrowser.open(auth_url)
    except Exception:
        pass
    server.handle_request()
    if not server.auth_code:
        raise GoogleAuthError("No se recibio codigo OAuth.")
    body = urllib.parse.urlencode({
        "client_id": client["client_id"],
        "client_secret": client["client_secret"],
        "code": server.auth_code,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
    }).encode("utf-8")
    token = _post_json(token_uri, body)
    token["expires_at"] = int(time.time()) + int(token.get("expires_in", 3600))
    save_token(token_path, token)
    return token_path


def _post_json(url: str, body: bytes) -> dict[str, Any]:
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


class _OAuthCallbackServer(HTTPServer):
    auth_code: str | None = None


class _OAuthCallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        self.server.auth_code = params.get("code", [None])[0]
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"Autorizacion completada. Puedes cerrar esta ventana.")

    def log_message(self, format: str, *args: object) -> None:
        return
