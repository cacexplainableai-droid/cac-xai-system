"""Creates the database and fills it with SYNTHETIC (made-up) sample data.

The proposal (Section 2.2, Data quality) allows anonymised or hypothetical records to be used
for testing. Nothing here is real church data. Run:  python seed_data.py
"""
import os
import random
from datetime import date, timedelta, datetime

import numpy as np
from werkzeug.security import generate_password_hash

import config
from db import init_db

SEED = 2026
START = date(2023, 1, 1)      # first Sunday of the data
END = date(2026, 10, 4)       # last Sunday of the data

FIRST = ["Mohamed", "Aminata", "Fatmata", "Isatu", "Abu", "Sorie", "Alusine", "Hawa", "Mariama", "Ibrahim",
         "Foday", "Kadiatu", "Joseph", "Mary", "Samuel", "Abigail", "Emmanuel", "Memunatu", "Santigie", "Zainab",
         "David", "Ruth", "Lahai", "Marie", "Alieu", "Josephine", "Patrick", "Beatrice", "Sahr", "Yabom",
         "Musa", "Rugiatu", "Tamba", "Salamatu", "Amara", "Finda", "Victor", "Grace", "Bockarie", "Naomi"]
LAST = ["Kamara", "Conteh", "Koroma", "Sesay", "Bangura", "Turay", "Jalloh", "Kanu", "Mansaray", "Bah",
        "Sankoh", "Kargbo", "Fofanah", "Cole", "Thomas", "Williams", "Macauley", "Johnson", "Taylor", "Davies",
        "Kawa", "Sandi", "Saio", "Barrie", "Lamin", "Massaquoi", "Gbla", "Samura", "Dumbuya", "Mbayo"]

MINISTRIES = [("Choir Ministry", "Music and worship"), ("Ushering Ministry", "Welcome and order in service"),
              ("Youth Ministry", "Ministry to young people"), ("Women's Ministry", "Fellowship and welfare of women"),
              ("Men's Fellowship", "Fellowship and service by men"), ("Children's Ministry", "Sunday school and children"),
              ("Evangelism Ministry", "Outreach and soul winning"), ("Prayer Ministry", "Intercession and prayer meetings")]

BASE_ATT = {1: 320, 2: 140, 3: 210, 4: 120}          # typical Sunday attendance in 2023
BASE_FIN = {1: 1.0, 2: 0.42, 3: 0.65, 4: 0.35}        # relative size of income
CATS = {"Tithes": 5200, "Offerings": 3100, "Thanksgiving": 1500, "Building Fund": 1800, "Welfare Fund": 700}  # SLE per week at HQ

SPECIALS = [("Easter Convention", (3, 4), 2.1), ("Annual Crusade", (6, 7), 2.4), ("Harvest Thanksgiving", (10, 11), 1.9),
            ("Christmas Service", (12, 12), 1.7), ("Women's Conference", (8, 8), 1.6)]


def name(rng):
    return f"{rng.choice(FIRST)} {rng.choice(LAST)}"


def seed(path=None, verbose=True):
    path = path or config.DB_PATH
    if os.path.exists(path):
        os.remove(path)
    conn = init_db(path)
    rng = random.Random(SEED)
    nrng = np.random.default_rng(SEED)
    c = conn.cursor()

    # --- users (passwords are stored hashed, never as plain text)
    users = [("cac-explainable-ai", "Michael Kamara (Group Leader)", "admin", "explainable_aigrp"),
             ("finance.officer", "Sallu Koroma (Finance Officer)", "finance", "Finance@2026"),
             ("branch.leader", "Joshua Saio Conteh (Branch Leader)", "leader", "Leader@2026")]
    for u, n, r, p in users:
        c.execute("INSERT INTO users(username,full_name,role,password_hash) VALUES(?,?,?,?)", (u, n, r, generate_password_hash(p)))

    for n, code, loc in config.BRANCHES:
        c.execute("INSERT INTO branches(name,code,location) VALUES(?,?,?)", (n, code, loc))

    # --- ministries per branch
    for b in range(1, 5):
        for m, d in MINISTRIES:
            c.execute("INSERT INTO ministries(name,leader,branch_id,description) VALUES(?,?,?,?)", (m, name(rng), b, d))
    n_min = len(MINISTRIES)

    # --- members
    for i in range(180):
        b = rng.choices([1, 2, 3, 4], weights=[4, 2, 3, 2])[0]
        mid = (b - 1) * n_min + rng.randint(1, n_min)
        jd = START + timedelta(days=rng.randint(-2000, 1300))
        c.execute("INSERT INTO members(full_name,gender,age_group,branch_id,ministry_id,phone,join_date,status) VALUES(?,?,?,?,?,?,?,?)",
                  (name(rng), rng.choice(["Male", "Female"]), rng.choices(["Children", "Youth", "Young Adults", "Adults", "Elders"], weights=[2, 3, 3, 4, 1])[0],
                   b, mid, f"+232 7{rng.randint(0,9)} {rng.randint(100000,999999)}", jd.isoformat(),
                   rng.choices(["Active", "Inactive"], weights=[9, 1])[0]))

    # --- attendance (Sunday service, midweek class, special events)
    special_days = {}
    for b in range(1, 5):
        for yr in range(2023, 2027):
            for title, months, mult in SPECIALS:
                mth = rng.choice(months)
                sundays = [START + timedelta(weeks=w) for w in range(0, 200)]
                cand = [d for d in sundays if d.year == yr and d.month == mth and d <= END]
                if cand:
                    special_days[(b, rng.choice(cand))] = (title, mult * rng.uniform(0.92, 1.08))
    d = START
    while d <= END:
        weeks = (d - START).days / 7
        for b in range(1, 5):
            growth = 1 + 0.0012 * weeks * (1.3 if b == 2 else 1.0)
            rainy = 0.90 if d.month in (7, 8) else (0.96 if d.month in (6, 9) else 1.0)
            level = BASE_ATT[b] * growth * rainy
            sp = special_days.get((b, d))
            if sp:
                att = level * sp[1] * nrng.normal(1, 0.04)
                stype, note = "Special Event", sp[0]
            else:
                att = level * nrng.normal(1, 0.05)
                stype, note = "Sunday Service", ""
            c.execute("INSERT INTO attendance(branch_id,service_date,service_type,attendance,notes) VALUES(?,?,?,?,?)",
                      (b, d.isoformat(), stype, int(round(att)), note))
            wed = d + timedelta(days=3)
            if wed <= END:
                mid_att = level * 0.34 * nrng.normal(1, 0.07)
                c.execute("INSERT INTO attendance(branch_id,service_date,service_type,attendance,notes) VALUES(?,?,?,?,?)",
                          (b, wed.isoformat(), "Midweek Bible Class", int(round(mid_att)), ""))
        d += timedelta(days=7)

    # --- finances: one record per category per week per branch, plus planted anomalies for evaluation
    d = START
    fin_rows = []
    while d <= END:
        weeks = (d - START).days / 7
        for b in range(1, 5):
            for cat, base in CATS.items():
                season = 1.35 if d.month == 12 else (1.15 if d.month in (3, 4, 10) else 1.0)
                amt = base * BASE_FIN[b] * (1 + 0.0015 * weeks) * season * nrng.normal(1, 0.10)
                amt = max(50, round(amt / 5) * 5 + rng.choice([0, 5, 10, 15]))
                if amt % 1000 == 0:
                    amt += 5
                tx = d + timedelta(days=rng.choice([0, 0, 0, 1]))
                fin_rows.append([b, tx.isoformat(), cat, float(amt), rng.choice(["Treasurer", "Finance Secretary"]), "", 0])
        d += timedelta(days=7)
    # plant 16 unusual transactions (these labels are used ONLY to evaluate the detector)
    idx = rng.sample(range(len(fin_rows)), 16)
    for k, i in enumerate(idx):
        r = fin_rows[i]
        if k % 4 == 0:      # unusually large round amount on a weekday
            r[3] = float(round(r[3] * rng.uniform(7, 12) / 1000) * 1000)
            r[1] = (date.fromisoformat(r[1]) + timedelta(days=rng.choice([2, 3, 4]))).isoformat()
            r[5] = "Posted late, no counterfoil"
        elif k % 4 == 1:    # unusually small amount
            r[3] = float(rng.choice([20, 35, 50]))
            r[5] = "Amount much lower than usual"
        elif k % 4 == 2:    # duplicate entry on the same day
            fin_rows.append([r[0], r[1], r[2], r[3], r[4], "Duplicate entry", 1])
            r[6] = 1
            continue
        else:               # large amount, odd weekday
            r[3] = float(round(r[3] * rng.uniform(5, 8) / 5) * 5)
            r[1] = (date.fromisoformat(r[1]) + timedelta(days=rng.choice([2, 3, 4, 5]))).isoformat()
        r[6] = 1
    for r in fin_rows:
        c.execute("INSERT INTO finances(branch_id,tx_date,category,amount,recorded_by,note,injected_anomaly) VALUES(?,?,?,?,?,?,?)", r)

    # --- events
    for b, dt in sorted(special_days, key=lambda k: k[1]):
        if dt >= date(2026, 1, 1):
            c.execute("INSERT INTO events(title,branch_id,event_date,event_type,expected_attendance,status,notes) VALUES(?,?,?,?,?,?,?)",
                      (special_days[(b, dt)][0], b, dt.isoformat(), "Special Service", None, "Completed" if dt <= date(2026, 10, 4) else "Planned", ""))
    upcoming = [("Harvest Thanksgiving 2026", 1, "2026-11-01", "Special Service"), ("Annual Youth Conference", 3, "2026-11-15", "Conference"),
                ("Christmas Carol Night", 2, "2026-12-20", "Special Service"), ("Watchnight Service", 4, "2026-12-31", "Special Service"),
                ("Evangelism Crusade", 1, "2026-11-22", "Crusade")]
    for t, b, dt, ty in upcoming:
        c.execute("INSERT INTO events(title,branch_id,event_date,event_type,expected_attendance,status,notes) VALUES(?,?,?,?,?,?,?)",
                  (t, b, dt, ty, None, "Planned", "Planning in progress"))

    # --- outreach
    kinds = ["Evangelism", "Community Development", "Welfare", "Donation Drive", "Medical Outreach"]
    for i in range(36):
        b = rng.randint(1, 4)
        dt = START + timedelta(days=rng.randint(0, 1380))
        k = rng.choice(kinds)
        c.execute("INSERT INTO outreach(branch_id,activity_date,activity_type,title,beneficiaries,cost,notes) VALUES(?,?,?,?,?,?,?)",
                  (b, dt.isoformat(), k, f"{k} - {rng.choice(['Wellington','Kissy Mess Mess','Waterloo','Kenema Town','Dwazark','Calaba Town','Grafton'])}",
                   rng.randint(25, 400), float(rng.randint(5, 60) * 100), ""))

    # --- resources
    res = [("Toyota Hiace Bus", "Vehicle"), ("Keyboard (Yamaha)", "Musical instrument"), ("Drum set", "Musical instrument"),
           ("Projector (Epson)", "Projector"), ("Public Address System", "Sound equipment"), ("Main Auditorium", "Hall"), ("Meeting Room", "Hall")]
    for b in range(1, 5):
        for n_, t in res:
            if t == "Vehicle" and b == 4:
                continue
            c.execute("INSERT INTO resources(branch_id,name,resource_type,status,condition,notes) VALUES(?,?,?,?,?,?)",
                      (b, n_, t, rng.choices(["Available", "In use", "Under repair"], weights=[7, 2, 1])[0],
                       rng.choice(["Good", "Good", "Fair", "Needs service"]), ""))

    # --- approved documents for the knowledge assistant (sample text written for the prototype)
    from knowledge_seed import DOCUMENTS
    for t, cat, txt in DOCUMENTS:
        c.execute("INSERT INTO documents(title,category,content,added_on) VALUES(?,?,?,?)", (t, cat, txt, datetime.now().strftime("%Y-%m-%d")))
    conn.commit()
    if verbose:
        for t in ["branches", "members", "attendance", "finances", "events", "outreach", "resources", "documents"]:
            print(f"{t:12s} {conn.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]} rows")
    conn.close()


if __name__ == "__main__":
    seed()
    print("Database created: cac_xai.db")
