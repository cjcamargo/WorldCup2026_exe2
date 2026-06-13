from __future__ import annotations

import re
import shutil
from http.cookiejar import CookieJar
import urllib.error
import urllib.request
import urllib.parse
from pathlib import Path

from .google_auth import GoogleAuthError, get_access_token


class DriveDownloadError(RuntimeError):
    pass


def download_drive_xlsx_api(file_id: str, target: Path, auth_config: dict, root: Path, timeout: int = 60) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        token = get_access_token(
            root / auth_config["credentials_path"],
            root / auth_config["token_path"],
            auth_config["scopes"],
        )
        meta = _drive_api_json(
            f"https://www.googleapis.com/drive/v3/files/{urllib.parse.quote(file_id)}?fields=id,name,mimeType",
            token,
            timeout,
        )
        mime_type = meta.get("mimeType", "")
        if mime_type == "application/vnd.google-apps.spreadsheet":
            url = f"https://www.googleapis.com/drive/v3/files/{urllib.parse.quote(file_id)}/export?mimeType=application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        else:
            url = f"https://www.googleapis.com/drive/v3/files/{urllib.parse.quote(file_id)}?alt=media"
        data, content_type = _download_url(url, timeout, token=token)
    except GoogleAuthError as exc:
        raise DriveDownloadError(str(exc)) from exc
    except urllib.error.URLError as exc:
        raise DriveDownloadError(str(exc)) from exc
    if not _looks_like_xlsx(data, content_type):
        raise DriveDownloadError("Google Drive API did not return an xlsx file.")
    target.write_bytes(data)
    return target


def download_drive_xlsx(file_id: str, target: Path, timeout: int = 60) -> Path:
    """Download a public/shared Drive xlsx by file id.

    If Drive blocks direct downloads, place the file manually in inputs/ with
    the same file name and the caller will use that local fallback.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    urls = [
        f"https://docs.google.com/spreadsheets/d/{file_id}/export?format=xlsx",
        f"https://drive.google.com/uc?export=download&id={file_id}",
    ]
    data = b""
    content_type = ""
    last_error = ""
    for url in urls:
        try:
            data, content_type = _download_url(url, timeout)
            if _looks_like_xlsx(data, content_type):
                break
            confirm_url = _extract_confirm_url(data, file_id)
            if confirm_url:
                data, content_type = _download_url(confirm_url, timeout)
                if _looks_like_xlsx(data, content_type):
                    break
            last_error = "Drive returned an HTML page instead of an xlsx file."
        except urllib.error.URLError as exc:
            last_error = str(exc)
    if not _looks_like_xlsx(data, content_type):
        raise DriveDownloadError(last_error or "Could not download xlsx file.")
    target.write_bytes(data)
    return target


def _drive_api_json(url: str, token: str, timeout: int) -> dict:
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return __import__("json").loads(response.read().decode("utf-8"))


def _download_url(url: str, timeout: int, token: str | None = None) -> tuple[bytes, str]:
    cookie_jar = CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))
    headers = {"User-Agent": "Mozilla/5.0"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    with opener.open(req, timeout=timeout) as response:
        return response.read(), response.headers.get("Content-Type", "")


def _looks_like_xlsx(data: bytes, content_type: str) -> bool:
    if data.startswith(b"PK"):
        return True
    lowered = content_type.lower()
    return "spreadsheet" in lowered and not data[:500].lower().lstrip().startswith(b"<html")


def _extract_confirm_url(data: bytes, file_id: str) -> str | None:
    text = data[:200000].decode("utf-8", errors="ignore")
    match = re.search(r'href="([^"]*?confirm=[^"]+)"', text)
    if match:
        href = match.group(1).replace("&amp;", "&")
        if href.startswith("/"):
            return f"https://drive.google.com{href}"
        return href
    token = re.search(r"confirm=([0-9A-Za-z_]+)", text)
    if token:
        return f"https://drive.google.com/uc?export=download&confirm={token.group(1)}&id={file_id}"
    return None


def resolve_participant_file(
    participant: dict,
    downloads_dir: Path,
    inputs_dir: Path,
    refresh: bool,
    auth_config: dict | None = None,
    root: Path | None = None,
) -> Path:
    file_name = participant["file_name"]
    local_input = inputs_dir / file_name
    downloaded = downloads_dir / file_name
    if local_input.exists() and not refresh:
        return local_input
    if downloaded.exists() and not refresh:
        return downloaded
    try:
        if auth_config and auth_config.get("enabled") and root:
            return download_drive_xlsx_api(participant["drive_file_id"], downloaded, auth_config, root)
        return download_drive_xlsx(participant["drive_file_id"], downloaded)
    except DriveDownloadError:
        if local_input.exists():
            shutil.copy2(local_input, downloaded)
            return downloaded
        raise
