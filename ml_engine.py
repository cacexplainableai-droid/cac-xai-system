"""The AI part of the system.

1. Attendance model   - RandomForest predicts attendance for a branch/date/service type.
2. Income model       - GradientBoosting forecasts monthly income per branch.
3. Anomaly detector   - IsolationForest flags unusual financial records for HUMAN review.
4. Explainability     - exact Shapley values (the principle behind SHAP) say how much each
                        factor pushed a prediction up or down.
"""
import math
from datetime import date, datetime

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor, GradientBoostingRegressor, IsolationForest
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

import config

START = date(2023, 1, 1)
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
SERVICE_CODES = {"Sunday Service": 0, "Midweek Bible Class": 1, "Special Event": 2}
SERVICE_NAMES = {v: k for k, v in SERVICE_CODES.items()}

ATT_FEATURES = ["branch", "month", "service", "rainy", "lag1", "roll4", "trend"]
ATT_LABELS = {"branch": "Branch", "month": "Month of the year", "service": "Type of service", "rainy": "Rainy season (Jun-Sep)",
              "lag1": "Last regular attendance", "roll4": "Average of last 4 regular services", "trend": "Long-term growth trend"}
INC_FEATURES = ["branch", "month", "trend", "lag1", "lag2", "roll3"]
INC_LABELS = {"branch": "Branch", "month": "Month of the year", "trend": "Long-term growth trend",
              "lag1": "Income last month", "lag2": "Income two months ago", "roll3": "Average of last 3 months"}
ANO_FEATURES = ["amount_ratio", "weekday", "round_amount", "gap_days", "category"]
ANO_LABELS = {"amount_ratio": "Amount compared with the usual amount", "weekday": "Day of the week recorded",
              "round_amount": "Amount is a round thousand", "gap_days": "Days since the last record of this type",
              "category": "Income category"}
CATEGORIES = ["Tithes", "Offerings", "Thanksgiving", "Building Fund", "Welfare Fund"]
_CACHE = {}


# ------------------------------------------------------------------ explainability
def shapley_values(predict_fn, x, background):
    """Exact Shapley values for ONE row x.

    For every group (coalition) of features we keep the values of x for the group and replace the
    other features by values from background rows, then average the model output. The Shapley formula
    then shares the difference between the prediction and the average prediction fairly among features.
    Returns (phi, base_value, prediction) with  base_value + sum(phi) == prediction.
    """
    x = np.asarray(x, dtype=float)
    background = np.asarray(background, dtype=float)
    d, m = len(x), len(background)
    n = 2 ** d
    stack = np.repeat(background[None, :, :], n, axis=0)           # (n, m, d)
    for i in range(n):
        for j in range(d):
            if (i >> j) & 1:
                stack[i, :, j] = x[j]
    values = predict_fn(stack.reshape(-1, d)).reshape(n, m).mean(axis=1)
    fact = [math.factorial(k) for k in range(d + 1)]
    phi = np.zeros(d)
    for j in range(d):
        for i in range(n):
            if not (i >> j) & 1:
                size = bin(i).count("1")
                w = fact[size] * fact[d - size - 1] / fact[d]
                phi[j] += w * (values[i | (1 << j)] - values[i])
    return phi, float(values[0]), float(values[n - 1])


def _metrics(y, p):
    return dict(mae=float(mean_absolute_error(y, p)), rmse=float(math.sqrt(mean_squared_error(y, p))), r2=float(r2_score(y, p)))


def _log_run(conn, name, target, met, base_mae, ntr, nte, notes=""):
    conn.execute("INSERT INTO model_runs(run_on,model_name,target,mae,rmse,r2,baseline_mae,n_train,n_test,notes) VALUES(?,?,?,?,?,?,?,?,?,?)",
                 (datetime.now().strftime("%Y-%m-%d %H:%M"), name, target, met["mae"], met["rmse"], met["r2"], base_mae, ntr, nte, notes))
    conn.commit()


def invalidate():
    _CACHE.clear()


# ------------------------------------------------------------------ attendance
def _attendance_frame(conn):
    df = pd.read_sql_query("SELECT branch_id AS branch, service_date, service_type, attendance FROM attendance ORDER BY service_date, id", conn,
                           parse_dates=["service_date"])
    lag1, roll4, hist = [], [], {}
    for r in df.itertuples():
        base = "Sunday Service" if r.service_type == "Special Event" else r.service_type
        h = hist.get((r.branch, base), [])
        lag1.append(h[-1] if h else np.nan)
        roll4.append(float(np.mean(h[-4:])) if h else np.nan)
        if r.service_type != "Special Event":
            hist.setdefault((r.branch, base), []).append(r.attendance)
    df["lag1"], df["roll4"] = lag1, roll4
    df["month"] = df.service_date.dt.month
    df["service"] = df.service_type.map(SERVICE_CODES)
    df["rainy"] = df.month.isin([6, 7, 8, 9]).astype(int)
    df["trend"] = (df.service_date - pd.Timestamp(START)).dt.days / 7.0
    return df.dropna(subset=["lag1", "roll4"]).reset_index(drop=True)


def attendance_model(conn):
    key = ("att", conn.execute("SELECT COUNT(*), MAX(id) FROM attendance").fetchone()[:])
    if key in _CACHE:
        return _CACHE[key]
    df = _attendance_frame(conn)
    cut = pd.Timestamp("2026-01-01")
    tr, te = df[df.service_date < cut], df[df.service_date >= cut]
    rf = RandomForestRegressor(n_estimators=200, min_samples_leaf=2, random_state=42, n_jobs=-1)
    rf.fit(tr[ATT_FEATURES].values, tr.attendance.values)
    pred = rf.predict(te[ATT_FEATURES].values)
    met = _metrics(te.attendance, pred)
    base_mae = float(mean_absolute_error(te.attendance, te.lag1))      # baseline: "same as last time"
    sp = te[te.service == 2]
    sp_mae = float(mean_absolute_error(sp.attendance, rf.predict(sp[ATT_FEATURES].values))) if len(sp) else None
    sp_base = float(mean_absolute_error(sp.attendance, sp.lag1)) if len(sp) else None
    te = te.assign(pred=pred)
    type_mae = {int(k): float(mean_absolute_error(g.attendance, g.pred)) for k, g in te.groupby("service")}
    final = RandomForestRegressor(n_estimators=200, min_samples_leaf=2, random_state=42, n_jobs=-1).fit(df[ATT_FEATURES].values, df.attendance.values)
    imp = dict(zip(ATT_FEATURES, final.feature_importances_))
    out = dict(model=final, metrics=met, baseline_mae=base_mae, n_train=len(tr), n_test=len(te), frame=df,
               background=df[ATT_FEATURES].sample(40, random_state=1).values, importances=imp, special_mae=sp_mae, special_baseline=sp_base, type_mae=type_mae)
    _log_run(conn, "RandomForest (attendance)", "Attendance", met, base_mae, len(tr), len(te),
             f"Special events MAE {sp_mae:.1f} vs baseline {sp_base:.1f}" if sp_mae else "")
    _CACHE[key] = out
    return out


def predict_attendance(conn, branch_id, service_date, service_type):
    """Returns prediction dict with explanation for one planned service."""
    am = attendance_model(conn)
    df = am["frame"]
    d = pd.Timestamp(service_date)
    base = "Sunday Service" if service_type == "Special Event" else service_type
    hist = pd.read_sql_query("SELECT attendance FROM attendance WHERE branch_id=? AND service_type=? AND service_date<? ORDER BY service_date",
                             conn, params=(branch_id, base, d.strftime("%Y-%m-%d")))["attendance"].tolist()
    if not hist:
        raise ValueError("Not enough history for this branch and service type.")
    x = [branch_id, d.month, SERVICE_CODES[service_type], int(d.month in (6, 7, 8, 9)), hist[-1], float(np.mean(hist[-4:])),
         (d - pd.Timestamp(START)).days / 7.0]
    fn = lambda X: am["model"].predict(X)
    phi, base_val, fx = shapley_values(fn, x, am["background"])
    # a simple +/- range from the model's typical error on the test period
    mae = am["type_mae"].get(SERVICE_CODES[service_type], am["metrics"]["mae"])   # error for THIS type of service
    return dict(prediction=int(round(fx)), low=int(round(fx - 1.5 * mae)), high=int(round(fx + 1.5 * mae)), base=base_val,
                contributions=_describe(ATT_FEATURES, ATT_LABELS, x, phi, _att_value), mae=mae)


def _att_value(f, v):
    if f == "branch": return config.BRANCHES[int(v) - 1][0]
    if f == "month": return MONTHS[int(v) - 1]
    if f == "service": return SERVICE_NAMES[int(v)]
    if f == "rainy": return "Yes" if v else "No"
    if f == "trend": return f"week {int(v)}"
    return f"{v:.0f}"


def _describe(features, labels, x, phi, valfn, unit="people"):
    items = []
    for f, v, p in zip(features, x, phi):
        items.append(dict(feature=f, label=labels[f], value=valfn(f, v), phi=float(p),
                          text=f"{labels[f]} ({valfn(f, v)}) {'raised' if p >= 0 else 'lowered'} the result by about {abs(p):,.0f} {unit}."))
    return sorted(items, key=lambda i: -abs(i["phi"]))


def _up(x):
    """Round UP to a whole number, ignoring tiny computer rounding errors (e.g. 110.00000000000001)."""
    return math.ceil(round(x, 6))


def plan_event(predicted):
    r = config.PLAN_RATIOS
    return dict(seats=_up(predicted * r["seat_buffer"]), volunteers=_up(predicted / r["attendees_per_volunteer"]),
                food=_up(predicted * r["food_portion_rate"]),
                parking=_up(predicted * r["share_arriving_by_vehicle"] / r["people_per_vehicle"]))


# ------------------------------------------------------------------ income forecast
def _monthly_frame(conn):
    df = pd.read_sql_query("SELECT branch_id AS branch, substr(tx_date,1,7) AS ym, SUM(amount) AS total FROM finances GROUP BY branch_id, ym ORDER BY ym", conn)
    rows = []
    for b, g in df.groupby("branch"):
        g = g.sort_values("ym").reset_index(drop=True)
        g = g.iloc[:-1] if len(g) > 1 and g.ym.iloc[-1] == g.ym.max() and _month_incomplete(g.ym.iloc[-1]) else g
        g["month"] = g.ym.str[5:7].astype(int)
        g["trend"] = np.arange(len(g))
        g["lag1"], g["lag2"] = g.total.shift(1), g.total.shift(2)
        g["roll3"] = g.total.shift(1).rolling(3).mean()
        rows.append(g)
    return pd.concat(rows).dropna().reset_index(drop=True), df


def _month_incomplete(ym):
    return ym >= "2026-10"          # the data ends on 4 Oct 2026, so October is incomplete


def income_model(conn):
    key = ("inc", conn.execute("SELECT COUNT(*), MAX(id) FROM finances").fetchone()[:])
    if key in _CACHE:
        return _CACHE[key]
    fr, raw = _monthly_frame(conn)
    cut = fr.ym.sort_values().unique()[-6]
    tr, te = fr[fr.ym < cut], fr[fr.ym >= cut]
    gb = GradientBoostingRegressor(n_estimators=250, max_depth=3, learning_rate=0.05, random_state=42).fit(tr[INC_FEATURES].values, tr.total.values)
    met = _metrics(te.total, gb.predict(te[INC_FEATURES].values))
    base_mae = float(mean_absolute_error(te.total, te.lag1))
    final = GradientBoostingRegressor(n_estimators=250, max_depth=3, learning_rate=0.05, random_state=42).fit(fr[INC_FEATURES].values, fr.total.values)
    out = dict(model=final, metrics=met, baseline_mae=base_mae, frame=fr, raw=raw, n_train=len(tr), n_test=len(te),
               background=fr[INC_FEATURES].sample(40, random_state=1).values)
    _log_run(conn, "GradientBoosting (monthly income)", "Income", met, base_mae, len(tr), len(te), "Last 6 complete months used for testing")
    _CACHE[key] = out
    return out


def forecast_income(conn, branch_id, months_ahead=3):
    im = income_model(conn)
    fr = im["frame"]
    g = fr[fr.branch == branch_id].sort_values("ym")
    hist = g.total.tolist()
    last_ym = g.ym.iloc[-1]
    y, m = int(last_ym[:4]), int(last_ym[5:])
    trend = int(g.trend.iloc[-1])
    out, expl = [], None
    for k in range(months_ahead):
        m += 1
        if m > 12: m, y = 1, y + 1
        trend += 1
        x = [branch_id, m, trend, hist[-1], hist[-2], float(np.mean(hist[-3:]))]
        p = float(im["model"].predict(np.array([x]))[0])
        if k == 0:
            phi, bv, fx = shapley_values(lambda X: im["model"].predict(X), x, im["background"])
            expl = _describe(INC_FEATURES, INC_LABELS, x, phi, _inc_value, unit="SLE")
        out.append(dict(ym=f"{y}-{m:02d}", label=f"{MONTHS[m-1][:3]} {y}", value=p))
        hist.append(p)
    return out, expl, g


def _inc_value(f, v):
    if f == "branch": return config.BRANCHES[int(v) - 1][0]
    if f == "month": return MONTHS[int(v) - 1]
    if f == "trend": return f"month {int(v)}"
    return f"SLE {v:,.0f}"


# ------------------------------------------------------------------ anomaly detection
def _tx_features(df):
    df = df.sort_values(["branch", "category", "tx_date", "id"]).copy()
    df["tx_date"] = pd.to_datetime(df.tx_date)
    med = df.groupby(["branch", "category"]).amount.transform("median")
    df["median_amount"] = med
    df["amount_ratio"] = df.amount / med
    df["weekday"] = df.tx_date.dt.weekday
    df["round_amount"] = ((df.amount % 1000 == 0) & (df.amount >= 1000)).astype(int)
    df["gap_days"] = df.groupby(["branch", "category"]).tx_date.diff().dt.days.fillna(7).clip(upper=30)
    df["category_code"] = df.category.map({c: i for i, c in enumerate(CATEGORIES)}).fillna(0)
    df["category"] = df["category_code"]
    return df


def run_anomaly_detection(conn, contamination=0.006):
    raw = pd.read_sql_query("SELECT id, branch_id AS branch, tx_date, category, amount, injected_anomaly FROM finances", conn)
    cat_name = raw.set_index("id").category.to_dict()
    fx = _tx_features(raw)
    X = fx[ANO_FEATURES].values
    iso = IsolationForest(n_estimators=300, contamination=contamination, random_state=42).fit(X)
    score = -iso.score_samples(X)                     # higher = more unusual
    flag = iso.predict(X) == -1
    fx["score"], fx["flag"] = score, flag
    conn.execute("UPDATE finances SET flagged=0, anomaly_score=NULL")
    conn.executemany("UPDATE finances SET flagged=?, anomaly_score=? WHERE id=?", [(int(f), float(s), int(i)) for f, s, i in zip(flag, score, fx.id)])
    conn.commit()
    tp = int(((fx.flag) & (fx.injected_anomaly == 1)).sum())
    ev = dict(flagged=int(flag.sum()), planted=int(fx.injected_anomaly.sum()), caught=tp,
              precision=tp / max(1, int(flag.sum())), recall=tp / max(1, int(fx.injected_anomaly.sum())))
    _log_run(conn, "IsolationForest (anomalies)", "Unusual transactions", dict(mae=0, rmse=0, r2=0), 0, len(fx), 0,
             f"flagged {ev['flagged']}; caught {tp} of {ev['planted']} planted; precision {ev['precision']:.2f}; recall {ev['recall']:.2f}")
    _CACHE["ano"] = dict(iso=iso, frame=fx, cat_name=cat_name)
    return ev


def explain_anomaly(conn, tx_id):
    if "ano" not in _CACHE:
        run_anomaly_detection(conn)
    a = _CACHE["ano"]
    fx = a["frame"]
    row = fx[fx.id == tx_id]
    if row.empty:
        return None
    row = row.iloc[0]
    x = [row[f] for f in ANO_FEATURES]
    bg = fx[ANO_FEATURES].sample(60, random_state=1).values
    phi, bv, val = shapley_values(lambda X: -a["iso"].score_samples(X), x, bg)
    items = _describe(ANO_FEATURES, ANO_LABELS, x, phi, _ano_value, unit="points")
    for it in items:
        it["text"] = f"{it['label']} ({it['value']}) {'made the record look more unusual' if it['phi'] >= 0 else 'made the record look more normal'} (impact {abs(it['phi']):.3f})."
    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    reasons = []
    if row.amount_ratio >= 2: reasons.append(f"the amount is about {row.amount_ratio:.1f} times the usual {a['cat_name'][tx_id]} amount for this branch")
    if row.amount_ratio <= 0.5: reasons.append(f"the amount is only {row.amount_ratio*100:.0f}% of the usual {a['cat_name'][tx_id]} amount for this branch")
    if row.round_amount: reasons.append("the amount is an exact round thousand, which is rare for this type of record")
    if row.weekday not in (6, 0): reasons.append(f"it was recorded on a {days[int(row.weekday)]}, while most records are made on Sunday or Monday")
    if row.gap_days <= 1: reasons.append("a record of the same type was made only a day or less earlier (possible duplicate)")
    if not reasons: reasons.append("the combination of its features differs from the usual pattern")
    return dict(score=float(row.score), flagged=bool(row.flag), contributions=items, base=bv, reasons=reasons,
                disclaimer="This is a statistical flag for human review. It is NOT a finding of wrongdoing.")


def _ano_value(f, v):
    if f == "amount_ratio": return f"{v:.1f} x usual"
    if f == "weekday": return ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][int(v)]
    if f == "round_amount": return "Yes" if v else "No"
    if f == "gap_days": return f"{v:.0f} days"
    return CATEGORIES[int(v)]
