import os
from functools import wraps

import psycopg2
from flask import Flask, redirect, render_template, request, session, url_for
from psycopg2.extras import RealDictCursor

from rules import liquor_digest, weigh

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET", "tea-cupping-dev-secret")

ACCOUNTS = {
    "taster": {"password": "tea123456", "role": "writer"},
    "observer": {"password": "look123456", "role": "reader"},
}


def db():
    return psycopg2.connect(os.environ["DATABASE_URL"])


def login_required(fn):
    @wraps(fn)
    def wrap(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("login"))
        return fn(*args, **kwargs)

    return wrap


@app.get("/health")
def health():
    return {"status": "ok", "service": "tea-blend-cupping"}


@app.route("/login", methods=["GET", "POST"])
def login():
    error = ""
    if request.method == "POST":
        name = request.form.get("username", "").strip()
        account = ACCOUNTS.get(name)
        if not account or account["password"] != request.form.get("password", ""):
            error = "用户名或密码错误"
        else:
            session["user"] = name
            session["role"] = account["role"]
            return redirect(url_for("home"))
    return render_template("login.html", error=error)


@app.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.get("/")
@login_required
def home():
    with db() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """SELECT c.*, s.digest AS liquor_digest
                 FROM cuppings c
            LEFT JOIN liquor_snapshots s ON s.cupping_id = c.id
             ORDER BY c.id DESC"""
        )
        rows = cur.fetchall()
    return render_template("home.html", rows=rows, can_write=session.get("role") == "writer")


@app.post("/cuppings")
@login_required
def create():
    if session.get("role") != "writer":
        return ("仅审评员可提交拼配审评", 403)
    aroma = float(request.form["aroma"])
    taste = float(request.form["taste"])
    liquor = float(request.form["liquor"])
    lot = request.form["lot"].strip()
    verdict, note, score = weigh(aroma, taste, liquor)
    with db() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """INSERT INTO cuppings (lot, aroma, taste, liquor, score, verdict, note, created_by)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
            (lot, aroma, taste, liquor, score, verdict, note, session["user"]),
        )
        row = cur.fetchone()
        conn.commit()
    if request.headers.get("HX-Request"):
        row["liquor_digest"] = None
        return render_template("_row.html", row=row)
    return redirect(url_for("home"))


@app.get("/snapshots")
@login_required
def snapshots():
    """汤色留影专页：可按审评编号翻当前有效留影与覆盖备忘列表。"""
    cupping_id_raw = request.args.get("cupping_id", "").strip()
    cupping_id = int(cupping_id_raw) if cupping_id_raw.isdigit() else None
    can_write = session.get("role") == "writer"

    cupping = None
    current = None
    memos = []
    with db() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """SELECT c.*, s.digest AS liquor_digest, s.caption, s.updated_at,
                      s.created_by AS snapshot_by
                 FROM cuppings c
            LEFT JOIN liquor_snapshots s ON s.cupping_id = c.id
             ORDER BY c.id DESC"""
        )
        all_rows = cur.fetchall()
        if cupping_id is not None:
            cupping = next((r for r in all_rows if r["id"] == cupping_id), None)
            if cupping:
                cur.execute(
                    """SELECT * FROM liquor_snapshot_memos
                        WHERE cupping_id = %s ORDER BY changed_at DESC, id DESC""",
                    (cupping_id,),
                )
                memos = cur.fetchall()
    return render_template(
        "snapshots.html",
        all_rows=all_rows,
        cupping=cupping,
        current=cupping,
        memos=memos,
        can_write=can_write,
    )


@app.post("/cuppings/<int:cupping_id>/snapshots")
@login_required
def upload_snapshot(cupping_id):
    """挂汤色留影：仅审评员、仅通过行；服务端按说明句算短串，覆盖须留备忘。"""
    if session.get("role") != "writer":
        return ("观察员只能查看留影，不能上传", 403)
    caption = request.form.get("caption", "").strip()
    if not caption:
        return ("说明句不能为空", 400)
    digest = liquor_digest(caption)
    operator = session["user"]
    with db() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM cuppings WHERE id = %s", (cupping_id,))
        cupping = cur.fetchone()
        if not cupping:
            return ("审评记录不存在", 404)
        if cupping["verdict"] != "通过":
            return ("不通过行禁止挂汤色留影", 403)
        cur.execute(
            "SELECT digest FROM liquor_snapshots WHERE cupping_id = %s",
            (cupping_id,),
        )
        old = cur.fetchone()
        old_digest = old["digest"] if old else None
        cur.execute(
            """INSERT INTO liquor_snapshots (cupping_id, caption, digest, created_by, updated_at)
               VALUES (%s,%s,%s,%s,now())
               ON CONFLICT (cupping_id) DO UPDATE
                  SET caption = EXCLUDED.caption,
                      digest = EXCLUDED.digest,
                      created_by = EXCLUDED.created_by,
                      updated_at = now()""",
            (cupping_id, caption, digest, operator),
        )
        if old_digest is not None and old_digest != digest:
            cur.execute(
                """INSERT INTO liquor_snapshot_memos
                       (cupping_id, old_digest, new_digest, changed_by, changed_at)
                   VALUES (%s,%s,%s,%s,now())""",
                (cupping_id, old_digest, digest, operator),
            )
        conn.commit()
    return redirect(url_for("snapshots", cupping_id=cupping_id))
