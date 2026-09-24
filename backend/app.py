import os
from functools import wraps

import psycopg2
from flask import Flask, abort, redirect, render_template, request, session, url_for
from psycopg2.extras import RealDictCursor

from rules import summarize_liquor, weigh

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


def writer_required(fn):
    @wraps(fn)
    def wrap(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("login"))
        if session.get("role") != "writer":
            return ("观察员只能查看，不能上传留影", 403)
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
            """SELECT c.*, s.summary AS liquor_summary
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
        row["liquor_summary"] = None
        conn.commit()
    if request.headers.get("HX-Request"):
        return render_template("_row.html", row=row)
    return redirect(url_for("home"))


@app.get("/snapshots")
@login_required
def snapshots_page():
    """汤色留影专页：可按审评编号翻当前有效留影与覆盖备忘列表。"""
    cupping_id_raw = request.args.get("cupping", "").strip()
    cupping_id = None
    focus = None
    overrides = []
    not_found = False
    if cupping_id_raw:
        try:
            cupping_id = int(cupping_id_raw)
        except ValueError:
            not_found = True
    with db() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """SELECT c.*, s.sentence AS shot_sentence, s.summary AS liquor_summary,
                      s.created_by AS shot_by, s.created_at AS shot_at
               FROM cuppings c
               LEFT JOIN liquor_snapshots s ON s.cupping_id = c.id
               ORDER BY c.id"""
        )
        all_rows = cur.fetchall()
        if cupping_id is not None:
            cur.execute(
                """SELECT c.*, s.sentence AS shot_sentence, s.summary AS liquor_summary,
                          s.created_by AS shot_by, s.created_at AS shot_at
                   FROM cuppings c
                   LEFT JOIN liquor_snapshots s ON s.cupping_id = c.id
                   WHERE c.id = %s""",
                (cupping_id,),
            )
            focus = cur.fetchone()
            if focus is None:
                not_found = True
            else:
                cur.execute(
                    """SELECT old_summary, new_summary, operator, changed_at
                       FROM liquor_overrides
                       WHERE cupping_id = %s
                       ORDER BY changed_at DESC, id DESC""",
                    (cupping_id,),
                )
                overrides = cur.fetchall()
    return render_template(
        "snapshots.html",
        all_rows=all_rows,
        focus=focus,
        overrides=overrides,
        cupping_query=cupping_id_raw,
        not_found=not_found,
        can_write=session.get("role") == "writer",
    )


@app.post("/cuppings/<int:cupping_id>/snapshots")
@writer_required
def upload_snapshot(cupping_id):
    """挂汤色留影：仅审评员、仅“通过”行。服务端据说明句算短串落库，不收大图文件。

    同一行再挂即覆盖：旧短串进覆盖备忘，列表只保留新短串。
    事后改正审评说明句不会回改短串——短串只能由本上传路径变更。
    """
    sentence = request.form.get("sentence", "").strip()
    if not sentence:
        return ("说明句不能为空", 400)
    operator = session["user"]
    with db() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM cuppings WHERE id = %s FOR UPDATE", (cupping_id,))
        cupping = cur.fetchone()
        if cupping is None:
            abort(404)
        if cupping["verdict"] != "通过":
            return ("不通过行禁止挂汤色留影", 403)
        new_summary = summarize_liquor(sentence)
        cur.execute(
            "SELECT * FROM liquor_snapshots WHERE cupping_id = %s FOR UPDATE",
            (cupping_id,),
        )
        old = cur.fetchone()
        old_summary = old["summary"] if old else None
        cur.execute(
            """INSERT INTO liquor_snapshots (cupping_id, sentence, summary, created_by)
               VALUES (%s, %s, %s, %s)
               ON CONFLICT (cupping_id) DO UPDATE
               SET sentence = EXCLUDED.sentence,
                   summary = EXCLUDED.summary,
                   created_by = EXCLUDED.created_by,
                   created_at = now()""",
            (cupping_id, sentence, new_summary, operator),
        )
        if old_summary is not None and old_summary != new_summary:
            cur.execute(
                """INSERT INTO liquor_overrides (cupping_id, old_summary, new_summary, operator)
                   VALUES (%s, %s, %s, %s)""",
                (cupping_id, old_summary, new_summary, operator),
            )
        conn.commit()
    return redirect(url_for("snapshots_page", cupping=cupping_id))
