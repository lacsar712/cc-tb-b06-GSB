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
    # 汤色留影：每个审评行至多一条“当前有效留影”。
    # 只落库服务端算出的摘要短串，不存大图文件；sentence 可改正，summary 一经上传即冻结。
    cur.execute(
        """CREATE TABLE IF NOT EXISTS liquor_snapshots (
            cupping_id integer PRIMARY KEY REFERENCES cuppings (id),
            sentence text NOT NULL,
            summary text NOT NULL,
            created_by text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now()
        )"""
    )
    # 覆盖备忘：每次“再走上传”换新短串时记一条，留痕旧短串/新短串/操作者/时刻。
    cur.execute(
        """CREATE TABLE IF NOT EXISTS liquor_overrides (
            id serial PRIMARY KEY,
            cupping_id integer NOT NULL REFERENCES cuppings (id),
            old_summary text NOT NULL,
            new_summary text NOT NULL,
            operator text NOT NULL,
            changed_at timestamptz NOT NULL DEFAULT now()
        )"""
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
