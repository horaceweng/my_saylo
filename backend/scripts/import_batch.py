"""Import the results of the Colab batch pipeline (see english-app/colab/) into data/app.sqlite.

Each result is one JSON file, already transcribed and translated — this only writes it into the database,
the same rows `services/pipeline.py` would have made. A video or episode whose link is already in the
library is skipped, so the same folder can be re-run safely (e.g. after adding more results to it).

Usage: uv run python scripts/import_batch.py <folder> [<folder> ...]
The folder is searched recursively for *.json files.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlmodel import Session

from app.db import engine, init_db
from app.services.batch_import import BatchImportError, import_item, parse_item


def main(folders: list[str]) -> int:
    if not folders:
        print(__doc__)
        return 1
    init_db()
    files: list[Path] = []
    for folder in folders:
        path = Path(folder)
        if not path.exists():
            print(f"找不到資料夾：{path}")
            return 1
        files += sorted(path.rglob("*.json"))
    if not files:
        print("沒有找到任何 .json 檔案")
        return 1

    imported = skipped = failed = 0
    with Session(engine) as session:
        for file in files:
            try:
                data = json.loads(file.read_text(encoding="utf-8"))
                item = parse_item(data)
                media = import_item(session, item)
            except (json.JSONDecodeError, BatchImportError) as e:
                print(f"✗ {file.name}：{e}")
                failed += 1
                continue
            if media is None:
                print(f"− {file.name}：已經有這個影片／集數了，略過")
                skipped += 1
            else:
                print(f"✓ {file.name} → media #{media.id}「{media.title}」（{len(item.segments)} 句）")
                imported += 1

    print(f"\n共 {len(files)} 個檔案：匯入 {imported}、略過 {skipped}（已存在）、失敗 {failed}")
    return 1 if failed and not imported else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
