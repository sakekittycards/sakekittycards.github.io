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


def run(cmd: list[str]) -> None:
    log("RUN " + " ".join(cmd))
    try:
        env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
        r = subprocess.run(cmd, cwd=str(HERE), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=900, env=env)
        tail = "\n".join((r.stdout or "").splitlines()[-25:])
        log("OUT:\n" + tail)
        if r.returncode != 0:
            log(f"  (exit {r.returncode}) stderr: {(r.stderr or '')[-400:]}")
    except Exception as e:
        log(f"  RUN FAILED: {type(e).__name__}: {e}")


def main() -> int:
    log("=== hourly sync start (mode=%s) ===" % ("LIVE" if LIVE else "DRY-RUN"))
    src = newest_export()
    if not src:
        log("no 'Collection - Card Ladder*.csv' in Downloads — nothing to sync; abort"); return 0
    age_h = (datetime.datetime.now().timestamp() - src.stat().st_mtime) / 3600.0
    try:
        rows = sum(1 for _ in src.open("r", encoding="utf-8-sig")) - 1
    except Exception as e:
        log(f"SAFETY ABORT: cannot read export: {e}"); return 1
    log(f"export: {src.name} | age {age_h:.1f}h | {rows} rows")
    if rows < 1:
        log("SAFETY ABORT: export has 0 data rows — refusing to touch the catalog"); return 1
    if age_h > MAX_AGE_H:
        log(f"export older than {MAX_AGE_H:.0f}h — skipping (drop a fresh Sake export to sync)"); return 0

    # GRADED: export-driven reconcile — match Square graded by Cert # to the
    # fresh Sake CardLadder export, reprice keepers (market x1.03), delete sold,
    # NEVER auto-add. Held certs excluded. (Replaced the stale pricing.csv path.)
    graded_flag = ["--live"] if LIVE else []
    run([sys.executable, "_sync_dryrun.py", str(src), *graded_flag])
    log("(auto-add is OFF: CL-only slabs are reported, never inserted — user-gated)")

    # SINGLES: price each Square single off the newest TCGplayer MyPricing export
    # by SKU (exact card/variant) -> TCG Market Price x1.03 -> price-only update.
    singles_flag = ["--live"] if LIVE else []
    run([sys.executable, "_site_reprice_singles.py", *singles_flag])

    # SEALED is handled by its own hourly task (SakeKitty-SealedReprice).
    log("=== hourly sync end (graded + singles%s) ===" % (" LIVE" if LIVE else " dry-run"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
