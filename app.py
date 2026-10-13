"""CAC Sierra Leone - Explainable AI Framework (prototype). Run with:  python app.py"""
import csv
import io
import os
from datetime import datetime, date, timedelta
from functools import wraps

from flask import (Flask, render_template, request, redirect, url_for, session, flash, Response, abort)
from werkzeug.security import check_password_hash

import config
import db
import ml_engine as ml
import knowledge
import charts

app = Flask(__name__)
app.secret_key = config.SECRET_KEY
app.teardown_appcontext(db.close_db)

SERVICE_TYPES = ["Sunday Service", "Midweek Bible Class", "Special Event"]
CATEGORIES = ml.CATEGORIES

# Which role may open which page (human oversight: role-based access, as in proposal Section 4.1)
ROLE_PAGES = {
    "admin": "*",
    "finance": {"dashboard", "branches", "finance", "anomalies", "reports", "assistant", "governance_view"},
    "leader": {"dashboard", "branches", "members", "attendance", "predict", "events", "outreach", "resources", "ministries", "assistant", "reports"},
}


def audit(action, detail=""):
    d = db.get_db()
    d.execute("INSERT INTO audit_log(ts,username,action,detail) VALUES(?,?,?,?)",
              (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), session.get("user", {}).get("username", "-"), action, detail))
    d.commit()


def allowed(page):
    role = session.get("user", {}).get("role")
    perm = ROLE_PAGES.get(role, set())
    return perm == "*" or page in perm


def guard(page):
    def deco(fn):
        @wraps(fn)
        def inner(*a, **k):
            if "user" not in session:
                return redirect(url_for("login"))
            if not allowed(page):
                flash("Your role is not allowed to open that page.", "error")
                return redirect(url_for("dashboard"))
            return fn(*a, **k)
        return inner
    return deco


@app.context_processor
def inject():
    return dict(user=session.get("user"), allowed=allowed, today=date(2026, 10, 6).isoformat(), nav_active=request.endpoint)


def q(sql, args=()):
    return db.get_db().execute(sql, args).fetchall()


def branch_list():
    return q("SELECT id, name FROM branches ORDER BY id")


# ------------------------------------------------------------------ login
@app.route("/", methods=["GET"])
def home():
    return redirect(url_for("dashboard"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u = q("SELECT * FROM users WHERE username=?", (request.form.get("username", "").strip(),))
        if u and check_password_hash(u[0]["password_hash"], request.form.get("password", "")):
            session["user"] = dict(id=u[0]["id"], username=u[0]["username"], full_name=u[0]["full_name"], role=u[0]["role"])
            audit("LOGIN", "successful")
            return redirect(url_for("dashboard"))
        audit("LOGIN_FAILED", request.form.get("username", ""))
        flash("Wrong username or password. Please try again.", "error")
    return render_template("login.html")


@app.route("/logout")
def logout():
    if "user" in session:
        audit("LOGOUT")
    session.clear()
    return redirect(url_for("login"))


# ------------------------------------------------------------------ dashboard + branches
@app.route("/dashboard")
@guard("dashboard")
def dashboard():
    stats = dict(
        members=q("SELECT COUNT(*) c FROM members WHERE status='Active'")[0]["c"],
        avg_att=round(q("SELECT AVG(attendance) a FROM (SELECT attendance FROM attendance WHERE service_type='Sunday Service' ORDER BY service_date DESC LIMIT 16)")[0]["a"] * 4),
        income=q("SELECT SUM(amount) s FROM finances WHERE tx_date>=date('2026-09-01') AND tx_date<'2026-10-01'")[0]["s"] or 0,
        flagged=q("SELECT COUNT(*) c FROM finances WHERE flagged=1 AND review_status='Not reviewed'")[0]["c"],
        upcoming=q("SELECT COUNT(*) c FROM events WHERE status='Planned'")[0]["c"])
    rows = q("SELECT service_date d, SUM(attendance) t FROM attendance WHERE service_type IN ('Sunday Service','Special Event') GROUP BY service_date ORDER BY d DESC LIMIT 26")[::-1]
    chart = charts.line_chart([r["d"][5:] for r in rows], [("All branches - total Sunday attendance", [r["t"] for r in rows], None)])
    ev = q("SELECT e.*, b.name branch FROM events e JOIN branches b ON b.id=e.branch_id WHERE e.status='Planned' ORDER BY event_date LIMIT 5")
    return render_template("dashboard.html", stats=stats, chart=chart, events=ev)


@app.route("/branches")
@guard("branches")
def branches():
    bl = branch_list()
    names = [b["name"].replace(" Branch", "").replace("Mission Headquarters", "HQ") for b in bl]
    att = [q("SELECT AVG(attendance) a FROM (SELECT attendance FROM attendance WHERE branch_id=? AND service_type='Sunday Service' ORDER BY service_date DESC LIMIT 8)", (b["id"],))[0]["a"] for b in bl]
    att_prev = [q("SELECT AVG(attendance) a FROM (SELECT attendance FROM attendance WHERE branch_id=? AND service_type='Sunday Service' ORDER BY service_date DESC LIMIT 8 OFFSET 52)", (b["id"],))[0]["a"] for b in bl]
    inc = [q("SELECT SUM(amount) s FROM finances WHERE branch_id=? AND tx_date>='2026-09-01' AND tx_date<'2026-10-01'", (b["id"],))[0]["s"] for b in bl]
    mem = [q("SELECT COUNT(*) c FROM members WHERE branch_id=? AND status='Active'", (b["id"],))[0]["c"] for b in bl]
    out = q("SELECT branch_id, COUNT(*) n, SUM(beneficiaries) p FROM outreach GROUP BY branch_id")
    outd = {r["branch_id"]: r for r in out}
    table = [dict(name=b["name"], members=mem[i], att=round(att[i]), growth=(att[i] / att_prev[i] - 1) * 100, income=inc[i],
                  outreach=outd[b["id"]]["n"], beneficiaries=outd[b["id"]]["p"]) for i, b in enumerate(bl)]
    c1 = charts.bar_chart(names, [("Average Sunday attendance (last 8 weeks)", [round(a) for a in att]), ("Same period one year earlier", [round(a) for a in att_prev])])
    c2 = charts.bar_chart(names, [("Income, September 2026 (SLE)", [round(i) for i in inc])])
    return render_template("branches.html", table=table, c1=c1, c2=c2)


# ------------------------------------------------------------------ generic management pages
ENT = {
    "members": dict(title="Members", page="members", fields=[
        ("full_name", "Full name", "text"), ("gender", "Gender", ["Male", "Female"]),
        ("age_group", "Age group", ["Children", "Youth", "Young Adults", "Adults", "Elders"]), ("branch_id", "Branch", "@branches"),
        ("ministry_id", "Ministry", "@ministries"), ("phone", "Phone", "text"), ("join_date", "Join date", "date"), ("status", "Status", ["Active", "Inactive"])],
        sql="SELECT m.id, m.full_name AS 'Full name', m.gender AS Gender, m.age_group AS 'Age group', b.name AS Branch, mi.name AS Ministry, m.status AS Status "
            "FROM members m JOIN branches b ON b.id=m.branch_id LEFT JOIN ministries mi ON mi.id=m.ministry_id ORDER BY m.id DESC LIMIT 150"),
    "ministries": dict(title="Ministries", page="ministries", fields=[
        ("name", "Ministry name", "text"), ("leader", "Leader", "text"), ("branch_id", "Branch", "@branches"), ("description", "Description", "text")],
        sql="SELECT mi.id, mi.name AS Ministry, mi.leader AS Leader, b.name AS Branch, mi.description AS Description FROM ministries mi JOIN branches b ON b.id=mi.branch_id ORDER BY b.id, mi.id"),
    "events": dict(title="Events", page="events", fields=[
        ("title", "Event title", "text"), ("branch_id", "Branch", "@branches"), ("event_date", "Event date", "date"),
        ("event_type", "Type", ["Special Service", "Conference", "Crusade"]), ("status", "Status", ["Planned", "Completed", "Cancelled"]), ("notes", "Notes", "text")],
        sql="SELECT e.id, e.title AS Event, b.name AS Branch, e.event_date AS Date, e.event_type AS Type, e.status AS Status FROM events e JOIN branches b ON b.id=e.branch_id ORDER BY e.event_date DESC",
        link=("Plan this event", "/events/{id}/plan")),
    "outreach": dict(title="Community Outreach", page="outreach", fields=[
        ("branch_id", "Branch", "@branches"), ("activity_date", "Date", "date"),
        ("activity_type", "Type", ["Evangelism", "Community Development", "Welfare", "Donation Drive", "Medical Outreach"]),
        ("title", "Activity title", "text"), ("beneficiaries", "Beneficiaries", "number"), ("cost", "Cost (SLE)", "number"), ("notes", "Notes", "text")],
        sql="SELECT o.id, o.activity_date AS Date, b.name AS Branch, o.activity_type AS Type, o.title AS Activity, o.beneficiaries AS Beneficiaries, o.cost AS 'Cost (SLE)' "
            "FROM outreach o JOIN branches b ON b.id=o.branch_id ORDER BY o.activity_date DESC LIMIT 100"),
    "resources": dict(title="Resources", page="resources", fields=[
        ("branch_id", "Branch", "@branches"), ("name", "Resource name", "text"),
        ("resource_type", "Type", ["Vehicle", "Musical instrument", "Projector", "Sound equipment", "Hall"]),
        ("status", "Status", ["Available", "In use", "Under repair"]), ("condition", "Condition", ["Good", "Fair", "Needs service"]), ("notes", "Notes", "text")],
        sql="SELECT r.id, b.name AS Branch, r.name AS Resource, r.resource_type AS Type, r.status AS Status, r.condition AS Condition FROM resources r JOIN branches b ON b.id=r.branch_id ORDER BY b.id, r.resource_type"),
}


def field_options(spec):
    if spec == "@branches":
        return [(b["id"], b["name"]) for b in branch_list()]
    if spec == "@ministries":
        return [("", "(none)")] + [(m["id"], f'{m["name"]} - {m["code"]}') for m in q("SELECT m.id, m.name, b.code FROM ministries m JOIN branches b ON b.id=m.branch_id ORDER BY b.id, m.id")]
    return [(v, v) for v in spec]


@app.route("/manage/<entity>", methods=["GET", "POST"])
def manage(entity):
    if entity not in ENT:
        abort(404)
    cfg = ENT[entity]
    if "user" not in session:
        return redirect(url_for("login"))
    if not allowed(cfg["page"]):
        flash("Your role is not allowed to open that page.", "error")
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        vals, names = [], []
        for name, label, kind in cfg["fields"]:
            v = request.form.get(name, "").strip()
            if v == "" and name not in ("notes", "phone", "ministry_id", "description", "cost", "beneficiaries"):
                flash(f"Please fill in: {label}", "error")
                return redirect(url_for("manage", entity=entity))
            if kind == "number":
                try:
                    v = float(v or 0)
                    if v < 0: raise ValueError
                except ValueError:
                    flash(f"{label} must be a positive number.", "error")
                    return redirect(url_for("manage", entity=entity))
            if name == "ministry_id" and v == "":
                v = None
            names.append(name); vals.append(v)
        d = db.get_db()
        d.execute(f"INSERT INTO {entity}({','.join(names)}) VALUES({','.join('?'*len(names))})", vals)
        d.commit()
        audit("ADD_" + entity.upper(), str(vals[:2]))
        flash(f"{cfg['title']} record saved.", "ok")
        return redirect(url_for("manage", entity=entity))
    rows = q(cfg["sql"])
    fields = [(n, l, field_options(k) if k not in ("text", "date", "number") else None, k) for n, l, k in cfg["fields"]]
    return render_template("manage.html", cfg=cfg, entity=entity, rows=rows, fields=fields)


# ------------------------------------------------------------------ attendance + prediction
@app.route("/attendance", methods=["GET", "POST"])
@guard("attendance")
def attendance():
    d = db.get_db()
    if request.method == "POST":
        try:
            n = int(request.form["attendance"])
            if n < 0 or n > 20000: raise ValueError
            date.fromisoformat(request.form["service_date"])
            assert request.form["service_type"] in SERVICE_TYPES
        except Exception:
            flash("Please enter a valid date, service type and attendance number.", "error")
            return redirect(url_for("attendance"))
        d.execute("INSERT INTO attendance(branch_id,service_date,service_type,attendance,notes) VALUES(?,?,?,?,?)",
                  (request.form["branch_id"], request.form["service_date"], request.form["service_type"], n, request.form.get("notes", "")))
        d.commit(); ml.invalidate(); audit("ADD_ATTENDANCE", f"{request.form['service_date']} {n}")
        flash("Attendance saved. The prediction model will include it automatically.", "ok")
        return redirect(url_for("attendance"))
    bid = int(request.args.get("branch", 1))
    rows = q("SELECT service_date, attendance FROM attendance WHERE branch_id=? AND service_type='Sunday Service' ORDER BY service_date DESC LIMIT 52", (bid,))[::-1]
    chart = charts.line_chart([r["service_date"][2:] for r in rows], [("Sunday attendance", [r["attendance"] for r in rows], None)])
    ages = q("SELECT age_group, COUNT(*) c FROM members WHERE branch_id=? GROUP BY age_group", (bid,))
    recent = q("SELECT a.id, a.service_date, b.name branch, a.service_type, a.attendance, a.notes FROM attendance a JOIN branches b ON b.id=a.branch_id ORDER BY a.service_date DESC, a.id DESC LIMIT 12")
    return render_template("attendance.html", branches=branch_list(), bid=bid, chart=chart, ages=ages, recent=recent, types=SERVICE_TYPES)


@app.route("/predict", methods=["GET", "POST"])
@guard("predict")
def predict():
    res = None
    form = dict(branch_id="1", service_date="2026-10-11", service_type="Sunday Service")
    am = ml.attendance_model(db.get_db())
    if request.method == "POST":
        form = {k: request.form.get(k, "") for k in form}
        try:
            date.fromisoformat(form["service_date"])
            res = ml.predict_attendance(db.get_db(), int(form["branch_id"]), form["service_date"], form["service_type"])
            res["plan"] = ml.plan_event(res["prediction"])
            res["chart"] = charts.contribution_chart(res["contributions"], unit="people")
            res["branch"] = config.BRANCHES[int(form["branch_id"]) - 1][0]
            audit("PREDICT_ATTENDANCE", f"{res['branch']} {form['service_date']} {form['service_type']} -> {res['prediction']}")
        except Exception as e:
            flash(f"Could not make a prediction: {e}", "error")
    return render_template("predict.html", res=res, form=form, branches=branch_list(), types=SERVICE_TYPES, am=am)


@app.route("/events/<int:eid>/plan")
@guard("events")
def event_plan(eid):
    ev = q("SELECT e.*, b.name branch FROM events e JOIN branches b ON b.id=e.branch_id WHERE e.id=?", (eid,))
    if not ev:
        abort(404)
    ev = ev[0]
    res = ml.predict_attendance(db.get_db(), ev["branch_id"], ev["event_date"], "Special Event")
    res["plan"] = ml.plan_event(res["prediction"])
    res["chart"] = charts.contribution_chart(res["contributions"], unit="people")
    audit("PLAN_EVENT", f"{ev['title']} -> {res['prediction']}")
    return render_template("event_plan.html", ev=ev, res=res, ratios=config.PLAN_RATIOS)


# ------------------------------------------------------------------ finance
@app.route("/finance", methods=["GET", "POST"])
@guard("finance")
def finance():
    d = db.get_db()
    if request.method == "POST":
        try:
            amt = float(request.form["amount"]); assert 0 < amt < 100_000_000
            date.fromisoformat(request.form["tx_date"]); assert request.form["category"] in CATEGORIES
        except Exception:
            flash("Please enter a valid date, category and a positive amount.", "error")
            return redirect(url_for("finance"))
        d.execute("INSERT INTO finances(branch_id,tx_date,category,amount,recorded_by,note) VALUES(?,?,?,?,?,?)",
                  (request.form["branch_id"], request.form["tx_date"], request.form["category"], amt, session["user"]["full_name"], request.form.get("note", "")))
        d.commit(); ml.invalidate(); audit("ADD_FINANCE", f"{request.form['category']} {amt}")
        flash("Income record saved. Run anomaly detection again to include it in the review.", "ok")
        return redirect(url_for("finance"))
    bid = int(request.args.get("branch", 1))
    fc, expl, hist = ml.forecast_income(d, bid, 3)
    labels = [m for m in hist.ym.tolist()[-24:]] + [f["ym"] for f in fc]
    hv = hist.total.tolist()[-24:]
    chart = charts.line_chart(labels, [("Actual monthly income (SLE)", hv + [None] * 3, None),
                                       ("Forecast (SLE)", [None] * (len(hv) - 1) + [hv[-1]] + [f["value"] for f in fc], "#b8892b")], forecast_from=len(hv) - 1)
    cats = q("SELECT category, SUM(amount) s FROM finances WHERE branch_id=? AND tx_date>='2026-01-01' GROUP BY category ORDER BY s DESC", (bid,))
    recent = q("SELECT f.id, f.tx_date, b.name branch, f.category, f.amount, f.recorded_by FROM finances f JOIN branches b ON b.id=f.branch_id ORDER BY f.tx_date DESC, f.id DESC LIMIT 10")
    m = ml.income_model(d)
    return render_template("finance.html", branches=branch_list(), bid=bid, fc=fc, expl=expl, chart=chart, cats=cats, recent=recent,
                           contrib=charts.contribution_chart(expl, unit="SLE"), cat_list=CATEGORIES, m=m)


@app.route("/anomalies", methods=["GET", "POST"])
@guard("anomalies")
def anomalies():
    d = db.get_db()
    ev = None
    if request.method == "POST":
        ev = ml.run_anomaly_detection(d)
        audit("RUN_ANOMALY_DETECTION", f"flagged {ev['flagged']}")
        flash(f"Detection finished: {ev['flagged']} records flagged for human review.", "ok")
    rows = q("SELECT f.id, f.tx_date, b.name branch, f.category, f.amount, f.anomaly_score, f.review_status FROM finances f JOIN branches b ON b.id=f.branch_id WHERE f.flagged=1 ORDER BY f.anomaly_score DESC")
    sel = request.args.get("tx")
    detail = None
    if sel:
        if not rows and "ano" not in ml._CACHE:
            ml.run_anomaly_detection(d)
        detail = ml.explain_anomaly(d, int(sel))
        if detail:
            detail["chart"] = charts.contribution_chart(detail["contributions"], unit="")
            detail["row"] = q("SELECT f.*, b.name branch FROM finances f JOIN branches b ON b.id=f.branch_id WHERE f.id=?", (int(sel),))[0]
    return render_template("anomalies.html", rows=rows, detail=detail, ev=ev)


@app.route("/anomalies/<int:tx>/review", methods=["POST"])
@guard("anomalies")
def review(tx):
    status = request.form.get("status")
    if status not in ("Reviewed - genuine", "Needs follow-up", "Not reviewed"):
        abort(400)
    d = db.get_db()
    d.execute("UPDATE finances SET review_status=? WHERE id=?", (status, tx))
    d.commit(); audit("REVIEW_FLAG", f"record {tx}: {status}")
    flash("Review decision recorded by a human reviewer.", "ok")
    return redirect(url_for("anomalies", tx=tx))


# ------------------------------------------------------------------ knowledge assistant
@app.route("/assistant", methods=["GET", "POST"])
@guard("assistant")
def assistant():
    d = db.get_db()
    results, question = None, ""
    if request.method == "POST" and request.form.get("form") == "add" and session["user"]["role"] == "admin":
        t, c, body = request.form.get("title", "").strip(), request.form.get("category", ""), request.form.get("content", "").strip()
        if t and body:
            d.execute("INSERT INTO documents(title,category,content,added_on) VALUES(?,?,?,?)", (t, c, body, date.today().isoformat()))
            d.commit(); audit("ADD_DOCUMENT", t); flash("Approved document added.", "ok")
    elif request.method == "POST":
        question = request.form.get("question", "")
        results = knowledge.search(d, question)
        audit("ASK_ASSISTANT", question[:80])
    docs = q("SELECT id, title, category, added_on FROM documents ORDER BY id")
    return render_template("assistant.html", results=results, question=question, docs=docs)


# ------------------------------------------------------------------ governance + reports
@app.route("/governance")
@guard("governance")
def governance():
    d = db.get_db()
    am, im = ml.attendance_model(d), ml.income_model(d)
    runs = q("SELECT * FROM model_runs ORDER BY id DESC LIMIT 8")
    log = q("SELECT * FROM audit_log ORDER BY id DESC LIMIT 15")
    users = q("SELECT username, full_name, role FROM users")
    imp = sorted(am["importances"].items(), key=lambda kv: -kv[1])
    imp_items = [dict(label=ml.ATT_LABELS[k], phi=v) for k, v in imp]
    return render_template("governance.html", am=am, im=im, runs=runs, log=log, users=users, imp=charts.contribution_chart(imp_items, unit=""))


REPORTS = {
    "attendance": ("Attendance records", "SELECT a.service_date AS date, b.name AS branch, a.service_type, a.attendance FROM attendance a JOIN branches b ON b.id=a.branch_id ORDER BY a.service_date"),
    "income": ("Income records", "SELECT f.tx_date AS date, b.name AS branch, f.category, f.amount FROM finances f JOIN branches b ON b.id=f.branch_id ORDER BY f.tx_date"),
    "flagged": ("Flagged records for review", "SELECT f.tx_date AS date, b.name AS branch, f.category, f.amount, f.anomaly_score, f.review_status FROM finances f JOIN branches b ON b.id=f.branch_id WHERE f.flagged=1 ORDER BY f.anomaly_score DESC"),
    "members": ("Membership summary", "SELECT b.name AS branch, m.age_group, COUNT(*) AS members FROM members m JOIN branches b ON b.id=m.branch_id GROUP BY b.name, m.age_group"),
    "outreach": ("Outreach report", "SELECT o.activity_date AS date, b.name AS branch, o.activity_type, o.title, o.beneficiaries, o.cost FROM outreach o JOIN branches b ON b.id=o.branch_id ORDER BY o.activity_date"),
}


@app.route("/reports")
@guard("reports")
def reports():
    allowed_reports = {k: v for k, v in REPORTS.items() if session["user"]["role"] == "admin" or
                       (session["user"]["role"] == "finance" and k in ("income", "flagged")) or
                       (session["user"]["role"] == "leader" and k in ("attendance", "members", "outreach"))}
    return render_template("reports.html", reports=allowed_reports)


@app.route("/reports/<name>.csv")
@guard("reports")
def report_csv(name):
    if name not in REPORTS:
        abort(404)
    role = session["user"]["role"]
    if role == "finance" and name not in ("income", "flagged") or role == "leader" and name not in ("attendance", "members", "outreach"):
        abort(403)
    rows = q(REPORTS[name][1])
    buf = io.StringIO()
    w = csv.writer(buf)
    if rows:
        w.writerow(rows[0].keys())
        for r in rows: w.writerow(list(r))
    audit("EXPORT_REPORT", name)
    return Response(buf.getvalue(), mimetype="text/csv", headers={"Content-Disposition": f"attachment; filename={name}_report.csv"})


def ensure_database():
    if not os.path.exists(config.DB_PATH):
        import seed_data
        print("First run: creating the sample database ...")
        seed_data.seed(verbose=False)


if __name__ == "__main__":
    ensure_database()
    print("\nSystem is starting. Open your browser at:  http://127.0.0.1:5000\n")
    app.run(host="127.0.0.1", port=5000, debug=False)
