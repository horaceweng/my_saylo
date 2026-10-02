"""Create the first administrator: uv run python scripts/create_admin.py <username>

Phrases and recordings saved before accounts existed are given to this account. Run it again with another name to
add more admins (they get nothing from the old data: only rows nobody owns are handed over).
"""

import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlmodel import Session  # noqa: E402

from app.db import engine, init_db  # noqa: E402
from app.services import auth  # noqa: E402


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    password = getpass.getpass("密碼: ")
    if password != getpass.getpass("再輸入一次: "):
        print("兩次密碼不一樣")
        return 1
    init_db()
    with Session(engine) as session:
        try:
            user = auth.create_user(session, sys.argv[1], password, is_admin=True)
        except auth.AuthError as e:
            print(e)
            return 1
        name, moved = user.username, auth.claim_ownerless_rows(session, user.id)
    print(f"已建立管理員 {name}" + (f"，並把 {moved} 筆舊的片語／錄音歸給他" if moved else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
