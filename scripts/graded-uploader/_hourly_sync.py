"""Hourly Sake CardLadder -> Square reconciler (export-drop model).

Reads the NEWEST 'Collection - Card Ladder*.csv' in Downloads (you export the
Sake collection from CardLadder after clearing its human-check) and reconciles
the live Square graded catalog to match.

SAFETY: defaults to DRY-RUN (logs what WOULD change, touches nothing). Only when
SK_SYNC_LIVE=1 is set will it apply changes. Go-live is gated until the graded
rules are wired in (price-less on site + price = trimmed avg of 5 recent CL sold
x1.15) and a dry-run log has been reviewed.

Aborts (never deletes) if the export is missing, empty, or stale beyond a sane
age. Logs every run to _sync_log.txt.
"""
from __future__ import annotations
import os, sys, subprocess, datetime
from pathlib import Path

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

HERE = Path(__file__).resolve().parent
DOWN = Path.home() / "Downloads"
LOG = HERE / "_sync_log.txt"
LIVE = os.environ.get("SK_SYNC_LIVE", "0") == "1"
MAX_AGE_H = float(os.environ.get("SK_SYNC_MAX_AGE_H", "168"))  # ignore exports older than ~7d


def log(m: str) -> None:
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {m}"
    print(line)
    try:
        with LOG.open("a", encoding="utf-8") as f: f.write(line + "\n")
    except Exception: pass


def newest_export() -> Path | None:
    files = sorted(DOWN.glob("Collection - Card Ladder*.csv"),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def run(cmd: list[str], cwd=None, env_extra=None) -> None:
    log("RUN " + " ".join(cmd) + (f"  (cwd={cwd})" if cwd else ""))
    try:
        env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", **(env_extra or {})}
        r = subprocess.run(cmd, cwd=str(cwd or HERE), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=900, env=env)
        tail = "\n".join((r.stdout or "").splitlines()[-25:])
        log("OUT:\n" + tail)
        if r.returncode != 0:
            log(f"  (exit {r.returncode}) stderr: {(r.stderr or '')[-400:]}")
    except Exception as e:
        log(f"  RUN FAILED: {type(e).__name__}: {e}")


def main() -> int:
    log("=== hourly sync start (mode=%s) ===" % ("LIVE" if LIVE else "DRY-RUN"))
    flag = ["--live"] if LIVE else []

    # GRADED: live cardladder.py (last-5-no-outlier x1.03) via the sk-queue, with
    # the eBay sanity-gate (suspect cards -> eBay last-sold). Needs worker.py up +
    # its CardLadder session valid AND restarted to load the fixed grade regex.
    # Gated on a fresh Sake CardLadder export; if missing/stale, SKIP graded only
    # (singles + sealed still run — they have their own sources).
    src = newest_export()
    skip_graded = ""
    if not src:
        skip_graded = "no 'Collection - Card Ladder*.csv' in Downloads"
    else:
        age_h = (datetime.datetime.now().timestamp() - src.stat().st_mtime) / 3600.0
        try:
            rows = sum(1 for _ in src.open("r", encoding="utf-8-sig")) - 1
        except Exception as e:
            rows, skip_graded = 0, f"cannot read export: {e}"
        if not skip_graded and rows < 1:
            skip_graded = "export has 0 data rows"
        elif not skip_graded and age_h > MAX_AGE_H:
            skip_graded = f"export older than {MAX_AGE_H:.0f}h (drop a fresh Sake export)"
        else:
            log(f"graded export: {src.name} | age {age_h:.1f}h | {rows} rows")
    if skip_graded:
        log(f"GRADED skipped: {skip_graded}")
    else:
        run([sys.executable, "_reprice_graded_verify.py", str(src), *flag])

    # SINGLES (raw): each Square single by SKU -> newest TCGplayer MyPricing
    # export "TCG Market Price" x1.03 -> price-only update.
    run([sys.executable, "_site_reprice_singles.py", *flag])

    # SEALED: tcgsearch -> Square (Airtable-backed). Bundled into this hourly run
    # (was a separate SakeKitty-SealedReprice task — now consolidated here).
    sealed_dir = HERE.parent / "sealed-inventory"
    run([sys.executable, "_sealed_reprice.py"], cwd=sealed_dir,
        env_extra=({} if LIVE else {"DRY_RUN": "1"}))

    log("=== hourly sync end (graded + singles + sealed%s) ===" % (" LIVE" if LIVE else " dry-run"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
