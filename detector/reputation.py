"""
Reputation / crowdsourced layer — the part a forger CANNOT defeat by copying
file structure, because it checks the *data* and its history, not the bytes.

Three signals:
1. SBP operation-id format sanity  (catches lazy fakes with malformed ids)
2. operation-id reuse              (same SBP id + different requisites = recycled receipt)
3. known-fake hash / id database   (users report a fake → it never passes again, for anyone)
"""

import os
import re
import sqlite3
import hashlib
import time
import datetime

from .sbp_cipher import extract_sbp_opid

_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reputation.db")

# Genuine T-Bank SBP operation ids observed: 27 chars, start with a letter,
# uppercase+digits only, and end with the T-Bank SBP member code "00117".
_OPID_CANDIDATE_RE = re.compile(r"[A-Z][0-9A-Z]{24,30}")
TBANK_SBP_SUFFIX = "00117"
OPID_LEN = 27

# Signal weights (kept consistent with detector/tbank.py scale)
W_OPID_FORMAT    = 45    # malformed SBP id
W_OPID_REUSE     = 85    # same id seen with different requisites
W_OPID_TIMESTAMP = 95    # id-encoded date/time contradicts the printed date
W_OPID_REF       = 75    # operation-reference block looks synthetic (letter-heavy)
W_KNOWN_FAKE     = 100   # exact file / id previously reported as fake

# Static known-fake file hashes used by the bot for non-T-Bank banks.
# These MUST live here — check_known_fake() is what handle_document calls.
KNOWN_FAKE_BY_SHA256: dict[str, dict[str, str]] = {
    "9ddc4942d9248cc6037734a2aadb0ff1d12419581189759ef291f5cc9da57286": {
        "bank": "vtb",
        "code": "VTB_KNOWN_FILE_F1",
    },
    "0f6562768c2c26d2bb3c568819cd7fdbe2e22083c3ff677d15f84b2cd3bf4db9": {
        "bank": "vtb",
        "code": "VTB_KNOWN_FILE_F2",
    },
    # Exact file pin — custom Telegram caption (user request).
    "48d5ba20bc67be30b8e59c5ec491ae38e6825b14d45e6e3fc546418303ff8d7f": {
        "bank": "tbank",
        "code": "TBANK_KNOWN_FILE_EASTER",
        "message": "а чего хочешь достичь в этой жизни ты старина?",
    },
    # Confirmed phone-shell clone (14.pdf): Jasper/OpenPDF bit-perfect vs intrabank
    # template; no SBP bank5/40817 handle — pinned until a stable structural rule exists.
    "5a370e30ebe6743ea24d8d77be9a9b1a7357a5d9d94082e5fb9d25f427599166": {
        "bank": "tbank",
        "code": "TBANK_KNOWN_FILE_PHONE_SHELL_14",
    },
    # SEQ T-Bank phone height=451, F2.glyf=1130 in 1106–1226 hole.
    "6d4d5eacd3fd13c97742f8f9c05454a6ffca59ae9bcf90d87788b2c8e252edec": {
        "bank": "tbank",
        "code": "TBANK_KNOWN_FILE_PHONE_F2_MIDGAP_1130",
    },
    # SEQ Alfa Oracle SBP (alfa_sbp_142944 / 143126), FF2 in 21132–21682 hole.
    "4feebd6e1219e32f10463e3d57ef54d1d461aabbcb76fad07966474e4050f01f": {
        "bank": "alfa",
        "code": "ALFA_KNOWN_FILE_SBP_FF2_MIDGAP_142944",
    },
    "c94364a434ae05915735428e909b27da0bfd33da80814e9b633f8caa44afc8ec": {
        "bank": "alfa",
        "code": "ALFA_KNOWN_FILE_SBP_FF2_MIDGAP_143126",
    },
    # SEQ Yandex Jasper/OpenPDF: locale /CreationDate + YSText-Regular maxp 915.
    "91453ff5970d7be3c5771439313b78d65d15b01db626d360ff787eabb3dfcc25": {
        "bank": "yandex",
        "code": "YANDEX_KNOWN_FILE_CREATIONDATE_MAXP",
    },
    # Sovkom Flying Saucer clone kit (OpenPDF 3.0.5 + foreign A62/00118 SBP id).
    "69587935b25c0bc9ed6c0f37eb85cabecb5a5b14b9a33eaf25ba04fc82c4becd": {
        "bank": "sovkom",
        "code": "SOVKOM_KNOWN_FILE_FS_305_CLONE",
    },
    # T-Bank SBP phone clone: G1/00117 slot=014/791103 with foreign (A,1) binding.
    "31d4b2a313f70c1a55a9853bf1bd14d73e53eecd0e27bc2af88384b16268fa3f": {
        "bank": "tbank",
        "code": "TBANK_KNOWN_FILE_SBP_SLOT014_CLONE",
    },
}

# Every genuine T-Bank SBP reference block (opid[11:17]) observed so far is
# numeric-dominant: at most ONE uppercase letter, last char always a digit.
# A reference with this many letters is machine-generated base36 → forged.
REF_MAX_LETTERS = 2

_DATE_RE = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})\s+(\d{2}):(\d{2}):(\d{2})")
_OPID_NUM_RE = re.compile(r"[A-Z]([0-9]{6,})")


# ── DB ────────────────────────────────────────────────────────────────────────

def _con():
    con = sqlite3.connect(_DB_PATH, timeout=10)
    con.execute("""
        CREATE TABLE IF NOT EXISTS seen_ops (
            opid       TEXT PRIMARY KEY,
            sig        TEXT,          -- amount|sender|receiver|bank
            amount     TEXT,
            sender     TEXT,
            receiver   TEXT,
            file_hash  TEXT,
            first_seen REAL,
            times_seen INTEGER DEFAULT 1
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS known_fakes (
            file_hash   TEXT PRIMARY KEY,
            opid        TEXT,
            reporter_id INTEGER,
            reported_at REAL
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS seen_files (
            file_hash  TEXT PRIMARY KEY,
            cnt        INTEGER DEFAULT 1,
            first_seen REAL
        )
    """)
    con.execute("CREATE INDEX IF NOT EXISTS idx_fake_opid ON known_fakes(opid)")
    # Blacklisted payout requisites of the receiver (phone / card / account).
    # This is the one thing a forger cannot change: where the money lands. Once a
    # scammer's receipt is reported, every future receipt to the same wallet is
    # flagged, no matter how the file/opid/font are regenerated.
    con.execute("""
        CREATE TABLE IF NOT EXISTS blacklist_requisites (
            req_key     TEXT PRIMARY KEY,
            reporter_id INTEGER,
            reported_at REAL,
            hits        INTEGER DEFAULT 0
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS email_receipts (
            rkey       TEXT PRIMARY KEY,   -- 'opid:<id>' or 'file:<sha256>'
            first_chat INTEGER,
            first_seen REAL,
            cnt        INTEGER DEFAULT 1
        )
    """)
    con.commit()
    return con


_SEEN_FILES_LIMIT = 10   # keep only the last N checked files

def record_seen(pdf_bytes: bytes) -> bool:
    """
    Rolling window of the last _SEEN_FILES_LIMIT checked files.
    Returns True if this exact file was already in the window.
    Old entries are pruned automatically to stay within the limit.
    """
    fh = file_hash(pdf_bytes)
    con = _con()
    try:
        row = con.execute("SELECT cnt FROM seen_files WHERE file_hash=?", (fh,)).fetchone()
        if row:
            con.execute("UPDATE seen_files SET cnt=cnt+1 WHERE file_hash=?", (fh,))
            con.commit()
            return True
        con.execute(
            "INSERT INTO seen_files(file_hash,cnt,first_seen) VALUES(?,1,?)",
            (fh, time.time()),
        )
        # Prune oldest entries beyond the limit
        con.execute("""
            DELETE FROM seen_files WHERE file_hash NOT IN (
                SELECT file_hash FROM seen_files
                ORDER BY first_seen DESC LIMIT ?
            )
        """, (_SEEN_FILES_LIMIT,))
        con.commit()
        return False
    finally:
        con.close()


def file_hash(pdf_bytes: bytes) -> str:
    return hashlib.sha256(pdf_bytes).hexdigest()


# ── operation-id extraction & format check ─────────────────────────────────────

def extract_opid(text: str) -> str | None:
    """Pull the SBP operation id out of the receipt's plain text."""
    best = None
    for m in _OPID_CANDIDATE_RE.finditer(text or ""):
        tok = m.group(0)
        if tok.endswith(TBANK_SBP_SUFFIX):
            # prefer the canonical-length token
            if best is None or abs(len(tok) - OPID_LEN) < abs(len(best) - OPID_LEN):
                best = tok
    if best:
        return best
    # fallback: longest letter-led alnum token near the id label
    cands = [m.group(0) for m in _OPID_CANDIDATE_RE.finditer(text or "")]
    return max(cands, key=len) if cands else None


def validate_opid(opid: str | None, text: str) -> tuple[bool, str]:
    """
    Full structural + semantic validation of a T-Bank SBP operation id.

    Genuine layout (27 chars):
        [0]      letter            — operation type
        [1:5]    4 digits          — (year-2020)*1000 + day-of-year
        [5:7]    2 digits          — hour in UTC (printed MSK - 3)
        [7:9]    2 digits          — minute of the operation
        [9:11]   2 digits          — second of the operation (±1)
        [11:17]  6 chars base36    — unique operation reference (numeric-dominant)
        [17]     letter            — separator (observed G or B, always a letter)
        [18:22]  4 digits          — channel/terminal code (genuine cluster ~1001-1020)
        [22:27]  '00117'           — T-Bank issuer code (constant)

    Returns (is_fake, reason). Only judges SBP receipts (skips if no id).
    """
    if not opid:
        return (False, "")

    # ── structure ──
    if len(opid) != 27:
        return (True, f"длина ID {len(opid)} вместо 27 символов")
    if not opid[0].isalpha():
        return (True, "ID не начинается с буквы")
    if not (opid[1:5].isdigit() and opid[5:7].isdigit()):
        return (True, "блок даты/времени в ID не числовой")
    if not opid[7:11].isdigit():
        return (True, "блок минут/секунд в ID не числовой")
    if not re.fullmatch(r"[0-9A-Z]{6}", opid[11:17]):
        return (True, "блок ссылки операции имеет неверный формат")
    # position 18 is a letter separator — observed values are G/B (NOT a fixed
    # 'G'); a digit here means the block layout is wrong.
    if not opid[17].isalpha():
        return (True, f"разделитель на позиции 18 не буква (там «{opid[17]}»)")
    if not opid[18:22].isdigit():
        return (True, "блок кода канала в ID не числовой")
    if not opid.endswith("00117"):
        return (True, "ID не оканчивается на код T-Банка «00117»")

    # ── semantics: embedded timestamp must match the printed date ──
    dm = _DATE_RE.search(text or "")
    if dm:
        try:
            d, mo, y, h, mi, s = map(int, dm.groups())
            dt = datetime.datetime(y, mo, d, h, mi, s)
            enc_doy  = int(opid[1:5]) % 1000
            enc_hour = int(opid[5:7])
            real_doy = dt.timetuple().tm_yday
            real_utc = (dt.hour - 3) % 24
            if abs(enc_doy - real_doy) > 1:
                return (True, f"в ID зашит день года {enc_doy}, а в чеке {real_doy} — "
                              "ID скопирован с другого чека")
            if enc_hour != real_utc and abs(enc_hour - real_utc) not in (0, 1, 23):
                return (True, f"в ID зашит час {enc_hour} UTC, а в чеке {real_utc} UTC")
            enc_min = int(opid[7:9])
            if abs(enc_min - dt.minute) > 1 and abs(enc_min - dt.minute) < 59:
                return (True, f"в ID зашита минута {enc_min}, а в чеке {dt.minute} — "
                              "время не совпадает, ID собран вручную")
            enc_sec = int(opid[9:11])
            if abs(enc_sec - dt.second) > 2 and abs(enc_sec - dt.second) < 58:
                return (True, f"в ID зашита секунда {enc_sec}, а в чеке {dt.second} — "
                              "время не совпадает, ID собран вручную")
        except ValueError:
            pass
    return (False, "")


def reference_anomaly(opid: str | None) -> tuple[bool, str]:
    """
    The 6-char operation reference (opid[11:17]) in genuine T-Bank receipts is
    numeric-dominant (observed: at most one letter, last char a digit). A fake
    generator emits random base36, producing letter-heavy references like
    '45TSHL'. Flag references with too many letters or a non-digit final char.
    Conservative: only judges well-formed 27-char SBP ids.
    """
    if not opid or len(opid) != 27:
        return (False, "")
    ref = opid[11:17]
    if not re.fullmatch(r"[0-9A-Z]{6}", ref):
        return (False, "")
    letters = sum(c.isalpha() for c in ref)
    if letters > REF_MAX_LETTERS:
        return (True, f"ссылка операции «{ref}» содержит {letters} букв(ы) — "
                      "у настоящих чеков T-Банка она почти полностью числовая, "
                      "это сгенерированный ID")
    return (False, "")


def opid_timestamp_mismatch(opid: str | None, text: str) -> tuple[bool, str]:
    """
    The SBP operation id embeds the transaction timestamp:
        digits 1-4 : (year-2020)*1000 + day-of-year   (so n % 1000 == day-of-year)
        digits 5-6 : hour in UTC  (printed time is MSK = UTC+3)
    A receipt that reuses an old id but shows a new date contradicts itself.
    Returns (is_mismatch, detail). Conservative: needs both id and printed date.
    """
    if not opid:
        return (False, "no opid")
    dm = _DATE_RE.search(text or "")
    nm = _OPID_NUM_RE.match(opid)
    if not dm or not nm:
        return (False, "no date/id")
    try:
        d, mo, y, h, mi, s = map(int, dm.groups())
        dt = datetime.datetime(y, mo, d, h, mi, s)
    except ValueError:
        return (False, "bad date")
    num = nm.group(1)
    enc_doy  = int(num[0:4]) % 1000
    enc_hour = int(num[4:6])
    real_doy = dt.timetuple().tm_yday
    real_utc = (dt.hour - 3) % 24
    # day-of-year is the strong signal (±1 tolerance for the UTC midnight boundary);
    # hour mismatch corroborates.
    doy_bad  = abs(enc_doy - real_doy) > 1
    hour_bad = enc_hour != real_utc and abs(enc_hour - real_utc) not in (0, 1, 23)
    detail = (f"в ID зашит день года {enc_doy} (час UTC {enc_hour}), "
              f"а в чеке указан день {real_doy} (час UTC {real_utc})")
    return (doy_bad or hour_bad, detail)


def opid_format_ok(opid: str | None) -> bool:
    if not opid:
        return True  # not an SBP receipt — don't penalise here
    return (
        len(opid) == OPID_LEN
        and opid[0].isalpha()
        and opid.isalnum()
        and opid.endswith(TBANK_SBP_SUFFIX)
    )


# ── reputation check ────────────────────────────────────────────────────────────

def check(pdf_bytes: bytes, parsed: dict, text: str) -> dict:
    """
    Returns {"score": int, "flags": [str], "opid": str|None, "file_hash": str}.
    Records the receipt for future reuse-detection (unless already a known fake).
    """
    flags: list[str] = []
    score = 0
    fh = file_hash(pdf_bytes)
    # Use the corpus-calibrated extractor (detector/tbank.py) so the id stored for
    # reuse-detection matches the real 32-char T-Bank SBP layout; fall back to the
    # legacy text scraper only when tbank can't read one.
    opid = extract_sbp_opid(text) or extract_opid(text)

    # Static exact-file registry (custom caption / known malicious SHA).
    meta = KNOWN_FAKE_BY_SHA256.get(fh)
    if meta:
        code = meta.get("code") or "KNOWN_FAKE_FILE"
        flags.append(
            f"[{code}] known fake SHA-256={fh} (bank={meta.get('bank', '?')})"
        )
        out = {
            "score": W_KNOWN_FAKE,
            "flags": flags,
            "opid": opid,
            "file_hash": fh,
            "known_fake": True,
        }
        if meta.get("message"):
            out["custom_message"] = meta["message"]
        return out

    con = _con()
    try:
        # 1) exact known fake (reported by users)
        row = con.execute(
            "SELECT reported_at FROM known_fakes WHERE file_hash=?", (fh,)
        ).fetchone()
        if not row and opid:
            row = con.execute(
                "SELECT reported_at FROM known_fakes WHERE opid=?", (opid,)
            ).fetchone()
        if row:
            flags.append(
                "Этот чек ранее был отмечен пользователями как ФЕЙК — "
                "он уже в базе подделок"
            )
            score += W_KNOWN_FAKE
            return {"score": score, "flags": flags, "opid": opid, "file_hash": fh}

        # 1b) blacklisted receiver requisites (un-forgeable payout wallet)
        req_bad, req_reason = check_requisites(parsed)
        if req_bad:
            flags.append(req_reason)
            score += W_KNOWN_FAKE
            return {"score": score, "flags": flags, "opid": opid, "file_hash": fh}

        # 2) SBP operation-id structure.
        #    Delegated entirely to the corpus-calibrated detector (detector/tbank.py),
        #    which already validates this and scores it in the main result. The old
        #    27-char / "00117"-suffix / position-17-letter model that used to live
        #    here is obsolete: NONE of the 23 reference originals match it, and it
        #    false-positived on genuine receipts carrying a "Сообщение" comment
        #    (their id layout differs). We no longer re-check structure here to
        #    avoid contradicting tbank and double-flagging.

        # 3) reuse detection
        if opid:
            sig = "|".join([
                str(parsed.get("amount", "")),
                str(parsed.get("sender", "")),
                str(parsed.get("receiver", "")),
                str(parsed.get("receiver_bank", "")),
            ])
            seen = con.execute(
                "SELECT sig, amount, receiver, times_seen FROM seen_ops WHERE opid=?",
                (opid,),
            ).fetchone()
            if seen:
                # reuse-detection flag disabled by request; keep counting only
                con.execute(
                    "UPDATE seen_ops SET times_seen=times_seen+1 WHERE opid=?", (opid,)
                )
            else:
                con.execute(
                    "INSERT INTO seen_ops(opid,sig,amount,sender,receiver,file_hash,first_seen,times_seen)"
                    " VALUES(?,?,?,?,?,?,?,1)",
                    (opid, sig, str(parsed.get("amount", "")),
                     str(parsed.get("sender", "")), str(parsed.get("receiver", "")),
                     fh, time.time()),
                )
                # Keep only the last 100 operation ids
                con.execute("""
                    DELETE FROM seen_ops WHERE opid NOT IN (
                        SELECT opid FROM seen_ops ORDER BY first_seen DESC LIMIT 100
                    )
                """)
        con.commit()
    finally:
        con.close()

    return {"score": score, "flags": flags, "opid": opid, "file_hash": fh}


def check_known_fake(pdf_bytes: bytes, text: str = "") -> dict:
    """
    Bank-agnostic reputation check for non-T-Bank receipts: static known-fake
    SHA registry + user-reported known-fakes database (by file hash) +
    forged-template detection via the PDF /ID.
    Returns the same shape as check().
    """
    flags: list[str] = []
    score = 0
    fh = file_hash(pdf_bytes)
    meta = KNOWN_FAKE_BY_SHA256.get(fh)
    if meta:
        code = meta.get("code") or "KNOWN_FAKE_FILE"
        flags.append(
            f"[{code}] known fake SHA-256={fh} (bank={meta.get('bank', '?')})"
        )
        score = max(score, W_KNOWN_FAKE)
    con = _con()
    try:
        row = con.execute(
            "SELECT reported_at FROM known_fakes WHERE file_hash=?", (fh,)
        ).fetchone()
        if row:
            flags.append(
                "Этот чек ранее был отмечен пользователями как ФЕЙК — "
                "он уже в базе подделок"
            )
            score = max(score, W_KNOWN_FAKE)
    finally:
        con.close()
    out = {
        "score": score,
        "flags": flags,
        "opid": None,
        "file_hash": fh,
        "known_fake": score >= W_KNOWN_FAKE,
    }
    if meta and meta.get("message"):
        out["custom_message"] = meta["message"]
    return out


# ── receiver payout requisites (the un-forgeable part) ─────────────────────────

def requisite_keys(parsed: dict | None) -> list[str]:
    """
    Stable, normalised payout identifiers of the receiver. A scammer reuses one
    wallet across endlessly-regenerated receipts, so these survive every change of
    file hash, opid, font prefix or /ID.

    Returns keys like 'phone:9996380686', 'card:220070XXXX1234', 'acct4:6515|эльмира и.'.
    """
    if not parsed:
        return []
    keys: list[str] = []
    cv = str(parsed.get("contact_value") or "")
    digits = re.sub(r"\D", "", cv)
    label = str(parsed.get("contact_label") or "").lower()
    if "телефон" in label or len(digits) >= 10:
        if len(digits) >= 10:
            keys.append("phone:" + digits[-10:])
    elif "карта" in label and len(digits) >= 6:
        keys.append("card:" + digits)

    acct = re.sub(r"\D", "", str(parsed.get("receiver_account") or ""))
    recv = str(parsed.get("receiver") or "").strip().lower()
    if len(acct) >= 6:
        keys.append("acct:" + acct)
    elif len(acct) == 4 and recv:
        # 4 digits alone collide too easily — pin to the receiver name
        keys.append("acct4:" + acct + "|" + recv)
    return keys


def blacklist_requisites(parsed: dict | None, reporter_id: int) -> int:
    """Add the receiver's payout requisites to the blacklist. Returns count newly added."""
    keys = requisite_keys(parsed)
    if not keys:
        return 0
    con = _con()
    try:
        added = 0
        for k in keys:
            ex = con.execute(
                "SELECT 1 FROM blacklist_requisites WHERE req_key=?", (k,)).fetchone()
            con.execute(
                "INSERT OR IGNORE INTO blacklist_requisites"
                "(req_key, reporter_id, reported_at, hits) VALUES(?,?,?,0)",
                (k, reporter_id, time.time()))
            if not ex:
                added += 1
        con.commit()
        return added
    finally:
        con.close()


def check_requisites(parsed: dict | None) -> tuple[bool, str]:
    """
    Flag a receipt whose receiver requisites were previously reported as a scam
    wallet. Conclusive and immune to file/opid/font regeneration.

    Returns (is_fake, reason).
    """
    keys = requisite_keys(parsed)
    if not keys:
        return (False, "")
    con = _con()
    try:
        for k in keys:
            row = con.execute(
                "SELECT 1 FROM blacklist_requisites WHERE req_key=?", (k,)).fetchone()
            if row:
                con.execute(
                    "UPDATE blacklist_requisites SET hits=hits+1 WHERE req_key=?", (k,))
                con.commit()
                kind = ("телефон" if k.startswith("phone")
                        else "карта" if k.startswith("card") else "счёт")
                return (True,
                        f"реквизиты получателя ({kind}) ранее отмечены как "
                        "мошеннические — на этот же кошелёк уже присылали поддельные "
                        "чеки; смена файла, ID и шрифта не помогает")
        return (False, "")
    finally:
        con.close()


def report_fake(file_hash_hex: str, opid: str | None, reporter_id: int) -> bool:
    """Add a receipt to the known-fakes database. Returns True if newly added."""
    con = _con()
    try:
        existing = con.execute(
            "SELECT 1 FROM known_fakes WHERE file_hash=?", (file_hash_hex,)
        ).fetchone()
        con.execute(
            "INSERT OR REPLACE INTO known_fakes(file_hash,opid,reporter_id,reported_at)"
            " VALUES(?,?,?,?)",
            (file_hash_hex, opid, reporter_id, time.time()),
        )
        con.commit()
        return existing is None
    finally:
        con.close()


# ── emailed-receipt reuse + freshness ──────────────────────────────────────────

# Labels that precede a transaction/operation identifier across banks.
_ID_LABELS = [
    "идентификатор операции", "номер операции", "id операции", "ид операции",
    "код операции", "номер документа", "номер квитанции", "номер платежа",
    "номер транзакции", "ссылка", "идентификатор платежа", "operation id",
    "номер операции в сбп", "id операции сбп",
]
# A reasonable id token: alnum (with - _) of length >= 8 (UUIDs, SBP ids, etc.)
_ID_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9\-_]{7,}")
_LONG_NUM_RE = re.compile(r"\d{12,}")


def extract_any_opid(text: str) -> str | None:
    """Bank-agnostic transaction identifier extraction (for reuse-dedup).

    Strategy, strongest first:
      1. T-Bank SBP id (existing, ends with 00117).
      2. Ozon 'po-<uuid>'.
      3. A token right after a known id label.
      4. A long (>=12 digit) numeric run.
    Returns a normalized id string or None.
    """
    t = text or ""
    # 1) T-Bank SBP
    sbp = extract_opid(t)
    if sbp and sbp.endswith(TBANK_SBP_SUFFIX):
        return sbp.upper()
    # 2) Ozon po-uuid
    mo = re.search(r"po-[0-9a-fA-F\-]{16,}", t)
    if mo:
        return mo.group(0).lower()
    # 3) token after a label
    low = t.lower()
    for label in _ID_LABELS:
        pos = low.find(label)
        if pos < 0:
            continue
        window = t[pos + len(label): pos + len(label) + 80]
        m = _ID_TOKEN_RE.search(window)
        if m and any(c.isdigit() for c in m.group(0)):
            return m.group(0)
    # 4) longest long-numeric run
    nums = _LONG_NUM_RE.findall(t)
    if nums:
        return max(nums, key=len)
    # 5) generic SBP-style token fallback
    return sbp.upper() if sbp else None


def receipt_key(pdf_bytes: bytes, text: str) -> str:
    """Stable identity of the underlying transaction.

    Prefer an extracted operation id (same across every resend of the same
    payment, for any bank); fall back to the file hash when none is found.
    """
    opid = extract_any_opid(text)
    return f"opid:{opid}" if opid else f"file:{file_hash(pdf_bytes)}"


def check_email_reuse(pdf_bytes: bytes, text: str, chat_id: int) -> dict:
    """Track every receipt that arrives by email and detect re-submission.

    Returns {"reused": bool, "by_other": bool, "cnt": int, "first_seen": float|None}.
    A genuine bank email proves the receipt is real, but a scammer can recycle
    one real receipt across many deals — this catches that.
    """
    rkey = receipt_key(pdf_bytes, text)
    con = _con()
    try:
        row = con.execute(
            "SELECT first_chat, first_seen, cnt FROM email_receipts WHERE rkey=?",
            (rkey,),
        ).fetchone()
        if row:
            first_chat, first_seen, cnt = row
            con.execute(
                "UPDATE email_receipts SET cnt=cnt+1 WHERE rkey=?", (rkey,)
            )
            con.commit()
            return {"reused": True, "by_other": int(first_chat) != int(chat_id),
                    "cnt": cnt + 1, "first_seen": first_seen}
        con.execute(
            "INSERT INTO email_receipts(rkey, first_chat, first_seen, cnt)"
            " VALUES(?,?,?,1)",
            (rkey, chat_id, time.time()),
        )
        con.execute("""
            DELETE FROM email_receipts WHERE rkey NOT IN (
                SELECT rkey FROM email_receipts ORDER BY first_seen DESC LIMIT 50
            )
        """)
        con.commit()
        return {"reused": False, "by_other": False, "cnt": 1, "first_seen": None}
    finally:
        con.close()


def receipt_age_hours(text: str) -> float | None:
    """Hours between the receipt's printed date (MSK) and now. None if no date."""
    dm = _DATE_RE.search(text or "")
    if not dm:
        return None
    try:
        d, mo, y, h, mi, s = map(int, dm.groups())
        dt = datetime.datetime(y, mo, d, h, mi, s)
    except ValueError:
        return None
    now_msk = datetime.datetime.utcnow() + datetime.timedelta(hours=3)
    return (now_msk - dt).total_seconds() / 3600.0


def stats() -> dict:
    con = _con()
    try:
        ops = con.execute("SELECT COUNT(*) FROM seen_ops").fetchone()[0]
        fakes = con.execute("SELECT COUNT(*) FROM known_fakes").fetchone()[0]
        return {"seen_ops": ops, "known_fakes": fakes}
    finally:
        con.close()
