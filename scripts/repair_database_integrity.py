"""Audit by default; --apply backs up and isolates orphan candidate records atomically.

No candidate identities are guessed or recreated. Run migrations before --apply.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3

ROOT = Path(__file__).resolve().parents[1]
SUPPORTED = {"candidate_vacancies", "candidate_stage_events", "interviews", "feedback",
             "candidate_transfers", "score_results", "chat_conversations"}


def repair_database(path: Path, *, apply: bool = False) -> dict:
    path = path.resolve(strict=True)
    connection = sqlite3.connect(path.as_uri() + "?mode=rw", uri=True, timeout=30)
    connection.row_factory = sqlite3.Row
    backup = None
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise RuntimeError("Database quick_check failed")
        violations = list(connection.execute("PRAGMA foreign_key_check"))
        summary = dict(Counter(row["table"] for row in violations))
        if not apply or not violations:
            return {"violations": len(violations), "tables": summary, "applied": False}
        folder = path.parent / "backups"
        folder.mkdir(exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
        backup = folder / f"{path.stem}_before_integrity_{stamp}.db"
        with sqlite3.connect(backup) as destination:
            connection.backup(destination)
        # Block concurrent writers and re-audit under the same transaction as repair.
        connection.execute("BEGIN IMMEDIATE")
        violations = list(connection.execute("PRAGMA foreign_key_check"))
        archived = detached = 0
        for violation in violations:
            table = violation["table"]
            if table not in SUPPORTED or violation["parent"] != "candidates":
                raise RuntimeError("Unsupported violation; repair rolled back")
            fk = next(row for row in connection.execute(f'PRAGMA foreign_key_list("{table}")')
                      if row["id"] == violation["fkid"])
            if fk["from"] != "candidate_id":
                raise RuntimeError("Unexpected foreign key; repair rolled back")
            row = dict(connection.execute(f'SELECT * FROM "{table}" WHERE rowid=?',
                                          (violation["rowid"],)).fetchone())
            connection.execute(
                "INSERT INTO integrity_archive (source_table,source_id,reason,original_row,archived_at) "
                "VALUES (?,?,?,?,?)",
                (table, str(row["id"]), "missing candidate: " + str(row["candidate_id"]),
                 json.dumps(row, ensure_ascii=False), datetime.now(timezone.utc).isoformat()),
            )
            if table == "chat_conversations":
                payload = json.loads(row["payload"])
                payload["candidate_id"] = None
                connection.execute("UPDATE chat_conversations SET candidate_id=NULL,payload=? WHERE id=?",
                                   (json.dumps(payload, ensure_ascii=False), row["id"]))
                detached += 1
            else:
                connection.execute(f'DELETE FROM "{table}" WHERE rowid=?', (violation["rowid"],))
                archived += 1
        if list(connection.execute("PRAGMA foreign_key_check")):
            raise RuntimeError("Remaining violations; repair rolled back")
        connection.commit()
        return {"violations_before": len(violations), "violations_after": 0,
                "archived": archived, "detached_conversations": detached,
                "backup": str(backup), "applied": True}
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path,
                        default=Path(os.getenv("SMARTHR_DATABASE", ROOT / "data/smarthr.db")))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(json.dumps(repair_database(args.database, apply=args.apply), ensure_ascii=False, indent=2))
