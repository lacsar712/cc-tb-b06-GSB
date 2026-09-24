import os
import time

import psycopg2

from rules import weigh


def connect():
    last = None
    for _ in range(30):
        try:
            return psycopg2.connect(os.environ["DATABASE_URL"])
        except psycopg2.OperationalError as exc:
            last = exc
            time.sleep(1)
    raise last


def main():
    conn = connect()
    cur = conn.cursor()
    cur.execute(
        """CREATE TABLE IF NOT EXISTS cuppings (
            id serial PRIMARY KEY,
            lot text NOT NULL,
            aroma double precision NOT NULL,
            taste double precision NOT NULL,
            liquor double precision NOT NULL,
            score double precision NOT NULL,
            verdict text NOT NULL,
            note text NOT NULL,
            created_by text NOT NULL
        )"""
    )
    # 汤色留影：只落由说明句算出的摘要短串，不存大图文件。
    # 一个审评只保留当前有效短串；覆盖历史进 liquor_snapshot_memos。
    cur.execute(
        """CREATE TABLE IF NOT EXISTS liquor_snapshots (
            cupping_id integer PRIMARY KEY REFERENCES cuppings(id),
            caption text NOT NULL,
            digest text NOT NULL,
            created_by text NOT NULL,
            updated_at timestamptz NOT NULL DEFAULT now()
        )"""
    )
    cur.execute(
        """CREATE TABLE IF NOT EXISTS liquor_snapshot_memos (
            id serial PRIMARY KEY,
            cupping_id integer NOT NULL REFERENCES cuppings(id),
            old_digest text,
            new_digest text NOT NULL,
            changed_by text NOT NULL,
            changed_at timestamptz NOT NULL DEFAULT now()
        )"""
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_liquor_memos_cupping "
        "ON liquor_snapshot_memos (cupping_id, changed_at DESC)"
    )
    cur.execute("SELECT COUNT(*) FROM cuppings")
    if cur.fetchone()[0] == 0:
        for lot, aroma, taste, liquor in (("春茶-A", 8, 8, 7), ("夏茶-C", 5, 4, 6)):
            verdict, note, score = weigh(aroma, taste, liquor)
            cur.execute(
                """INSERT INTO cuppings (lot, aroma, taste, liquor, score, verdict, note, created_by)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                (lot, aroma, taste, liquor, score, verdict, note, "taster"),
            )
    conn.commit()
    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
