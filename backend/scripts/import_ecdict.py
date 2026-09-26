"""Build data/dict.sqlite from ECDICT's stardict.db (downloaded to data/raw/).

Usage: uv run python scripts/import_ecdict.py
Converts the Chinese definitions to Traditional Chinese with OpenCC.
"""

import sqlite3
import sys
from pathlib import Path

from opencc import OpenCC

DATA = Path(__file__).resolve().parent.parent / "data"
SRC = DATA / "raw" / "stardict.db"
DST = DATA / "dict.sqlite"

COLUMNS = "word, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange"


def main() -> None:
    if not SRC.exists():
        sys.exit(f"找不到 {SRC}，請先下載並解壓 ecdict-sqlite-28.zip")
    cc = OpenCC("s2twp")
    DST.unlink(missing_ok=True)
    src = sqlite3.connect(SRC)
    dst = sqlite3.connect(DST)
    dst.execute(
        """CREATE TABLE dict (
            word TEXT PRIMARY KEY COLLATE NOCASE, phonetic TEXT, definition TEXT,
            translation TEXT, pos TEXT, collins INTEGER, oxford INTEGER, tag TEXT,
            bnc INTEGER, frq INTEGER, exchange TEXT)"""
    )
    rows = []
    for row in src.execute(f"SELECT {COLUMNS} FROM stardict"):
        row = list(row)
        row[3] = cc.convert(row[3]) if row[3] else row[3]
        rows.append(row)
        if len(rows) >= 50_000:
            dst.executemany("INSERT OR IGNORE INTO dict VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)
            rows.clear()
    if rows:
        dst.executemany("INSERT OR IGNORE INTO dict VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)
    dst.commit()
    count = dst.execute("SELECT COUNT(*) FROM dict").fetchone()[0]
    dst.close()
    print(f"匯入完成：{count} 個詞條 → {DST}")


if __name__ == "__main__":
    main()
