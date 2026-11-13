from __future__ import annotations

import csv
import io
import os
import secrets
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from flask import (
    Flask,
    Response,
    abort,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)


ROOT = Path(__file__).resolve().parent
INSTANCE = ROOT / "instance"
DATABASE = INSTANCE / "applications.sqlite3"
STATUSES = ("Applied", "Screening", "Interview", "Assessment", "Offer", "Rejected", "Withdrawn")
ACTIVE_STATUSES = ("Applied", "Screening", "Interview", "Assessment")
PIPELINE_STATUSES = ("Applied", "Screening", "Interview", "Assessment", "Offer")
WORK_MODES = ("Not specified", "Remote", "Hybrid", "On-site")

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get("FLASK_SECRET_KEY") or secrets.token_hex(32),
    MAX_CONTENT_LENGTH=1 * 1024 * 1024,
)
INSTANCE.mkdir(parents=True, exist_ok=True)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_error: BaseException | None = None) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db() -> None:
    with sqlite3.connect(DATABASE) as db:
        db.execute("PRAGMA journal_mode = WAL")
        db.execute(
            """CREATE TABLE IF NOT EXISTS applications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company TEXT NOT NULL,
                role TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'Applied',
                applied_date TEXT NOT NULL,
                job_url TEXT NOT NULL DEFAULT '',
                location TEXT NOT NULL DEFAULT '',
                work_mode TEXT NOT NULL DEFAULT 'Not specified',
                salary TEXT NOT NULL DEFAULT '',
                contact TEXT NOT NULL DEFAULT '',
                follow_up_date TEXT NOT NULL DEFAULT '',
                notes TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )"""
        )
        db.execute("CREATE INDEX IF NOT EXISTS idx_applications_status ON applications(status)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_applications_applied_date ON applications(applied_date)")


init_db()


def row_to_dict(row: sqlite3.Row | dict) -> dict:
    return {key: row[key] for key in row.keys()}


def get_application(application_id: int) -> sqlite3.Row:
    row = get_db().execute("SELECT * FROM applications WHERE id = ?", (application_id,)).fetchone()
    if row is None:
        abort(404, description="Application not found.")
    return row


def validate_application(data: dict, existing: sqlite3.Row | None = None) -> tuple[dict | None, dict]:
    """Return normalized fields and field-level errors shared by HTML and JSON routes."""
    fields = {
        "company": (existing["company"] if existing else "", 120),
        "role": (existing["role"] if existing else "", 160),
        "status": (existing["status"] if existing else "Applied", 30),
        "applied_date": (existing["applied_date"] if existing else date.today().isoformat(), 10),
        "job_url": (existing["job_url"] if existing else "", 500),
        "location": (existing["location"] if existing else "", 120),
        "work_mode": (existing["work_mode"] if existing else "Not specified", 30),
        "salary": (existing["salary"] if existing else "", 80),
        "contact": (existing["contact"] if existing else "", 160),
        "follow_up_date": (existing["follow_up_date"] if existing else "", 10),
        "notes": (existing["notes"] if existing else "", 4000),
    }
    cleaned: dict[str, str] = {}
    errors: dict[str, str] = {}
    for key, (fallback, limit) in fields.items():
        raw = data.get(key, fallback)
        if raw is None:
            raw = ""
        value = str(raw).strip()
        if len(value) > limit:
            errors[key] = f"Keep this field to {limit} characters or fewer."
        cleaned[key] = value

    if not cleaned["company"]:
        errors["company"] = "Company is required."
    if not cleaned["role"]:
        errors["role"] = "Role is required."
    if cleaned["status"] not in STATUSES:
        errors["status"] = "Choose one of the listed application stages."
    if cleaned["work_mode"] not in WORK_MODES:
        errors["work_mode"] = "Choose one of the listed work modes."
    for key in ("applied_date", "follow_up_date"):
        if cleaned[key]:
            try:
                date.fromisoformat(cleaned[key])
            except ValueError:
                errors[key] = "Enter a valid date in YYYY-MM-DD format."
    if cleaned["job_url"]:
        parsed = urlparse(cleaned["job_url"])
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            errors["job_url"] = "Use a full link starting with http:// or https://."

    return (None, errors) if errors else (cleaned, {})


def insert_application(fields: dict) -> int:
    now = utc_now()
    keys = tuple(fields.keys())
    placeholders = ", ".join("?" for _ in keys)
    cursor = get_db().execute(
        f"INSERT INTO applications ({', '.join(keys)}, created_at, updated_at) VALUES ({placeholders}, ?, ?)",
        tuple(fields[key] for key in keys) + (now, now),
    )
    get_db().commit()
    return int(cursor.lastrowid)


def update_application_record(application_id: int, fields: dict) -> None:
    now = utc_now()
    assignments = ", ".join(f"{key} = ?" for key in fields)
    get_db().execute(
        f"UPDATE applications SET {assignments}, updated_at = ? WHERE id = ?",
        tuple(fields.values()) + (now, application_id),
    )
    get_db().commit()


def filtered_applications(query: str = "", status: str = "") -> list[sqlite3.Row]:
    sql = "SELECT * FROM applications WHERE 1 = 1"
    params: list[str] = []
    if query:
        like = f"%{query}%"
        sql += " AND (company LIKE ? OR role LIKE ? OR location LIKE ?)"
        params.extend([like, like, like])
    if status and status in STATUSES:
        sql += " AND status = ?"
        params.append(status)
    sql += " ORDER BY applied_date DESC, id DESC"
    return get_db().execute(sql, params).fetchall()


@app.context_processor
def inject_globals() -> dict:
    return {"statuses": STATUSES, "work_modes": WORK_MODES, "today": date.today().isoformat()}


@app.get("/")
def index():
    query = request.args.get("q", "").strip()[:120]
    status = request.args.get("status", "")
    rows = filtered_applications(query, status)
    all_rows = get_db().execute("SELECT status FROM applications").fetchall()
    counts = {stage: 0 for stage in STATUSES}
    for row in all_rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    total = len(all_rows)
    active = sum(counts.get(stage, 0) for stage in ACTIVE_STATUSES)
    interviews = counts.get("Interview", 0) + counts.get("Assessment", 0)
    offers = counts.get("Offer", 0)
    responded = sum(counts.get(stage, 0) for stage in ("Screening", "Interview", "Assessment", "Offer", "Rejected"))
    response_rate = round(responded / total * 100) if total else 0
    return render_template(
        "index.html",
        applications=rows,
        counts=counts,
        query=query,
        selected_status=status,
        metrics={"total": total, "active": active, "interviews": interviews, "offers": offers, "response_rate": response_rate},
        pipeline_statuses=PIPELINE_STATUSES,
    )


@app.get("/applications/new")
def new_application():
    return render_template("application_form.html", application=None, form_action=url_for("create_application"))


@app.post("/applications")
def create_application():
    fields, errors = validate_application(request.form)
    if errors:
        for message in errors.values():
            flash(message, "error")
        return render_template("application_form.html", application=request.form, form_action=url_for("create_application")), 400
    application_id = insert_application(fields)
    flash("Application added to your tracker.", "success")
    return redirect(url_for("index", _anchor=f"application-{application_id}"))


@app.get("/applications/<int:application_id>/edit")
def edit_application(application_id: int):
    row = get_application(application_id)
    return render_template("application_form.html", application=row_to_dict(row), form_action=url_for("save_application", application_id=application_id))


@app.post("/applications/<int:application_id>")
def save_application(application_id: int):
    existing = get_application(application_id)
    fields, errors = validate_application(request.form, existing)
    if errors:
        for message in errors.values():
            flash(message, "error")
        application = row_to_dict(existing)
        application.update(request.form.to_dict())
        return render_template("application_form.html", application=application, form_action=url_for("save_application", application_id=application_id)), 400
    update_application_record(application_id, fields)
    flash("Application updated.", "success")
    return redirect(url_for("index", _anchor=f"application-{application_id}"))


@app.post("/applications/<int:application_id>/status")
def change_status(application_id: int):
    get_application(application_id)
    status = request.form.get("status", "")
    if status not in STATUSES:
        flash("Choose a valid stage.", "error")
    else:
        update_application_record(application_id, {"status": status})
        flash("Stage updated.", "success")
    return redirect(url_for("index", _anchor=f"application-{application_id}"))


@app.post("/applications/<int:application_id>/delete")
def delete_application(application_id: int):
    get_application(application_id)
    get_db().execute("DELETE FROM applications WHERE id = ?", (application_id,))
    get_db().commit()
    flash("Application deleted.", "success")
    return redirect(url_for("index"))


@app.get("/export.csv")
def export_csv():
    rows = get_db().execute("SELECT * FROM applications ORDER BY applied_date DESC, id DESC").fetchall()
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["Company", "Role", "Stage", "Applied date", "Job link", "Location", "Work mode", "Salary", "Contact", "Follow-up date", "Notes", "Created", "Updated"])
    for row in rows:
        values = [row[key] for key in ("company", "role", "status", "applied_date", "job_url", "location", "work_mode", "salary", "contact", "follow_up_date", "notes", "created_at", "updated_at")]
        writer.writerow([f"'{value}" if isinstance(value, str) and value.startswith(("=", "+", "-", "@", "\t", "\r")) else value for value in values])
    return Response(
        output.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=job-applications.csv"},
    )


@app.get("/health")
def health():
    total = get_db().execute("SELECT COUNT(*) FROM applications").fetchone()[0]
    return jsonify({"status": "ok", "application": "job-application-tracker", "database": "connected", "records": total})


@app.get("/api/applications")
def api_list_applications():
    query = request.args.get("q", "").strip()[:120]
    status = request.args.get("status", "")
    if status and status not in STATUSES:
        return jsonify({"error": "Invalid status.", "allowed_statuses": STATUSES}), 400
    rows = filtered_applications(query, status)
    return jsonify({"count": len(rows), "applications": [row_to_dict(row) for row in rows]})


@app.post("/api/applications")
def api_create_application():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Send a JSON object in the request body."}), 400
    fields, errors = validate_application(data)
    if errors:
        return jsonify({"error": "Validation failed.", "fields": errors}), 400
    application_id = insert_application(fields)
    row = get_application(application_id)
    return jsonify({"application": row_to_dict(row)}), 201


@app.route("/api/applications/<int:application_id>", methods=["GET", "PATCH", "DELETE"])
def api_application(application_id: int):
    row = get_application(application_id)
    if request.method == "GET":
        return jsonify({"application": row_to_dict(row)})
    if request.method == "DELETE":
        get_db().execute("DELETE FROM applications WHERE id = ?", (application_id,))
        get_db().commit()
        return Response(status=204)
    patch = request.get_json(silent=True)
    if not isinstance(patch, dict):
        return jsonify({"error": "Send a JSON object in the request body."}), 400
    fields, errors = validate_application(patch, row)
    if errors:
        return jsonify({"error": "Validation failed.", "fields": errors}), 400
    update_application_record(application_id, fields)
    return jsonify({"application": row_to_dict(get_application(application_id))})


@app.errorhandler(404)
def not_found(error):
    if request.path.startswith("/api/") or request.path == "/health":
        return jsonify({"error": getattr(error, "description", "Not found.")}), 404
    return render_template("404.html"), 404


if __name__ == "__main__":
    # Local-only by default. Use a production WSGI server before any public deployment.
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "5000")), debug=False)
