"""Java Deflater canonical zlib recompression (Oracle BI / OpenPDF profile)."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path

_JAVA_CP = Path(__file__).resolve().parents[1] / "tools" / "java_deflater"
_JAVA_CLASS = "CanonicalDeflater"
_ORACLE_LEVEL = 6


@lru_cache(maxsize=1)
def _java_bin() -> str | None:
    """Prefer a JDK that can load the shipped CanonicalDeflater class."""
    candidates: list[str] = []
    env = os.environ.get("JAVA_HOME")
    if env:
        candidates.append(str(Path(env) / "bin" / "java"))
    # Local Microsoft OpenJDK install (common on Windows CI/dev).
    ms = Path(r"C:\Program Files\Microsoft")
    if ms.is_dir():
        for jdk in sorted(ms.glob("jdk-*"), reverse=True):
            candidates.append(str(jdk / "bin" / "java"))
    which = shutil.which("java")
    if which:
        candidates.append(which)
    for cand in candidates:
        if not cand or not Path(cand).exists():
            continue
        try:
            probe = subprocess.run(
                [cand, "-version"],
                capture_output=True,
                timeout=15,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        # Reject ancient JRE that cannot load class file 61 (Java 17).
        err = (probe.stderr or b"") + (probe.stdout or b"")
        low = err.lower()
        if b"1.8." in low or b"version \"1." in low:
            # Still try — may work if class was compiled for 8.
            pass
        # Smoke: load our class.
        try:
            smoke = subprocess.run(
                [cand, "-cp", str(_JAVA_CP), _JAVA_CLASS],
                capture_output=True,
                timeout=15,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        # Usage exit 2 is success for class load; UnsupportedClassVersionError is fail.
        combined = (smoke.stderr or b"") + (smoke.stdout or b"")
        if b"UnsupportedClassVersionError" in combined:
            continue
        if smoke.returncode in (0, 1, 2) or b"usage:" in combined.lower():
            return cand
    return None


def java_deflate(decoded: bytes, *, level: int = _ORACLE_LEVEL) -> bytes | None:
    """Return zlib payload from Java ``new Deflater(level, false)``."""
    if decoded is None:
        return None
    java = _java_bin()
    if java is None:
        return None
    try:
        proc = subprocess.run(
            [
                java, "-cp", str(_JAVA_CP), _JAVA_CLASS,
                "--level", str(level), "--stdin",
            ],
            input=decoded,
            capture_output=True,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout


_MISSING = object()


def java_canonical_match(
    actual: bytes,
    decoded: bytes,
    *,
    level: int = _ORACLE_LEVEL,
    expected: bytes | None | object = _MISSING,
) -> tuple[bool, int, int, int]:
    """
    Compare actual compressed payload with Java canonical recompression.
    Returns (match, first_diff_offset, actual_byte, expected_byte).

    Pass ``expected`` from a prior ``java_deflate`` call to avoid a second JVM spawn.
    Explicit ``expected=None`` means Java was unavailable (no retry).
    """
    if expected is _MISSING:
        expected = java_deflate(decoded, level=level)
    if expected is None:
        return False, -1, -1, -1
    assert isinstance(expected, (bytes, bytearray))
    if actual == expected:
        return True, -1, -1, -1
    lim = min(len(actual), len(expected))
    for i in range(lim):
        if actual[i] != expected[i]:
            return False, i, actual[i], expected[i]
    return False, lim, -1, -1
def java_match_via_files(
    actual: bytes, decoded: bytes, *, level: int = _ORACLE_LEVEL
) -> tuple[bool, str]:
    """Independent file-based match check (second invocation path)."""
    java = _java_bin()
    if java is None:
        return False, "java_unavailable"
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        actual_path = base / "actual.bin"
        decoded_path = base / "decoded.bin"
        actual_path.write_bytes(actual)
        decoded_path.write_bytes(decoded)
        try:
            proc = subprocess.run(
                [
                    java, "-cp", str(_JAVA_CP), _JAVA_CLASS,
                    "--level", str(level),
                    "--match", str(actual_path), str(decoded_path),
                ],
                capture_output=True,
                text=True,
                timeout=120,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False, "java_unavailable"
        out = (proc.stdout or "").strip()
        if out == "MATCH":
            return True, out
        return False, out or (proc.stderr or "java_error").strip()
