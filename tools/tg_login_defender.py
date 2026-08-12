# -*- coding: utf-8 -*-
"""QR login for the detector Telegram watcher (separate session from fraudex).

Saves refreshing PNG → output/defender_qr.png
Scan: Telegram → Settings → Devices → Link Desktop Device
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

_DIR = Path(__file__).resolve().parent
_ROOT = _DIR.parent
_ZAP = Path(r"C:\Users\fanis\OneDrive\Desktop\ЗАПАСКА 13.07.26 WIP 31.07\tools")
sys.path.insert(0, str(_ZAP))

from tg_check_pdf import _load_env  # noqa: E402
from tg_client import connect_client, make_client  # noqa: E402

_PNG = _ROOT / "output" / "defender_qr.png"
_URL = _ROOT / "output" / "defender_qr_url.txt"
_SESSION = _DIR / ".tg_defender_session"


def _save_qr(url: str) -> None:
    import qrcode

    _PNG.parent.mkdir(parents=True, exist_ok=True)
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=10, border=2)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    img.save(_PNG)
    _URL.write_text(url, encoding="utf-8")
    print(f"QR refreshed → {_PNG}", flush=True)
    print("WAITING_SCAN", flush=True)


async def main() -> None:
    cfg = _load_env()
    cfg["TG_SESSION"] = str(_SESSION)
    print("=== Defender QR login (auto-refresh) ===", flush=True)
    print("Telegram → Настройки → Устройства → Подключить устройство", flush=True)
    print("Сканируй PNG: output/defender_qr.png (обновляется ~25с)", flush=True)

    client = make_client(cfg)
    await connect_client(client, cfg)
    if await client.is_user_authorized():
        me = await client.get_me()
        print(f"Already OK: {me.first_name} (@{me.username or '-'}) id={me.id}", flush=True)
        await client.disconnect()
        return

    from telethon.errors import SessionPasswordNeededError

    qr_login = await client.qr_login()
    _save_qr(qr_login.url)

    deadline = asyncio.get_event_loop().time() + 600
    refresh_every = 25.0
    last_refresh = asyncio.get_event_loop().time()

    while asyncio.get_event_loop().time() < deadline:
        try:
            await asyncio.wait_for(qr_login.wait(timeout=refresh_every), timeout=refresh_every + 2)
            break
        except (asyncio.TimeoutError, TimeoutError):
            now = asyncio.get_event_loop().time()
            if now - last_refresh >= refresh_every - 1:
                try:
                    await qr_login.recreate()
                    _save_qr(qr_login.url)
                    last_refresh = now
                    print("Сканируй НОВЫЙ QR", flush=True)
                except Exception as exc:
                    print(f"recreate fail: {exc}", flush=True)
                    qr_login = await client.qr_login()
                    _save_qr(qr_login.url)
                    last_refresh = now
            continue
        except SessionPasswordNeededError:
            print("NEED_2FA — напиши облачный пароль в чат", flush=True)
            await client.disconnect()
            return

    if not await client.is_user_authorized():
        print("NOT_AUTHORIZED — время вышло", flush=True)
        await client.disconnect()
        return

    me = await client.get_me()
    print(f"OK: {me.first_name} (@{me.username or '-'}) id={me.id}", flush=True)
    print(f"Session: {_SESSION}.session", flush=True)
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
