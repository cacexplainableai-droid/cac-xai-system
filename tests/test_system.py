"""Automated tests for the CAC Explainable AI system.  Run with:  python -m unittest tests.test_system -v
Each test has an ID (TC01...) that matches the test table in the project report."""
import os, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
import config

_TMP = os.path.join(tempfile.mkdtemp(), "test.db")
config.DB_PATH = _TMP                       # tests use their own database copy
import seed_data, db, ml_engine as ml, knowledge   # noqa: E402
import app as appmod                                  # noqa: E402

GROUP_USER, GROUP_PASS = "cac-explainable-ai", "explainable_aigrp"


def login(client, u=GROUP_USER, p=GROUP_PASS):
    return client.post("/login", data={"username": u, "password": p})


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        seed_data.seed(_TMP, verbose=False)
        ml.invalidate()
        cls.conn = db.connect(_TMP)
        appmod.app.config["TESTING"] = True


class UnitTests(Base):
    def test_TC01_shapley_matches_linear_model(self):
        """Shapley values of a linear model must equal coef x (x - background mean)."""
        bg = np.array([[0., 0.], [2., 4.]]); x = [3., 5.]
        phi, base, fx = ml.shapley_values(lambda X: 2 * X[:, 0] + 3 * X[:, 1], x, bg)
        self.assertAlmostEqual(phi[0], 2 * (3 - 1)); self.assertAlmostEqual(phi[1], 3 * (5 - 2))

    def test_TC02_shapley_efficiency_attendance(self):
        """base value + sum of contributions must equal the prediction."""
        r = ml.predict_attendance(self.conn, 1, "2026-11-01", "Special Event")
        self.assertAlmostEqual(r["base"] + sum(c["phi"] for c in r["contributions"]), r["prediction"], delta=1.0)

    def test_TC03_attendance_beats_baseline(self):
        am = ml.attendance_model(self.conn)
        self.assertLess(am["metrics"]["mae"], am["baseline_mae"])

    def test_TC04_attendance_r2_high(self):
        self.assertGreater(ml.attendance_model(self.conn)["metrics"]["r2"], 0.9)

    def test_TC05_special_event_higher_than_regular(self):
        a = ml.predict_attendance(self.conn, 1, "2026-11-01", "Special Event")["prediction"]
        b = ml.predict_attendance(self.conn, 1, "2026-11-01", "Sunday Service")["prediction"]
        self.assertGreater(a, b * 1.3)

    def test_TC06_event_plan_ratios(self):
        self.assertEqual(ml.plan_event(100), dict(seats=110, volunteers=4, food=80, parking=10))

    def test_TC07_income_forecast_three_positive_months(self):
        fc, expl, _ = ml.forecast_income(self.conn, 2, 3)
        self.assertEqual(len(fc), 3); self.assertTrue(all(f["value"] > 0 for f in fc)); self.assertEqual(len(expl), 6)

    def test_TC08_anomaly_detector_finds_planted_records(self):
        ev = ml.run_anomaly_detection(self.conn)
        self.assertGreater(ev["flagged"], 0); self.assertGreaterEqual(ev["recall"], 0.4)

    def test_TC09_anomaly_explanation_has_reasons(self):
        ml.run_anomaly_detection(self.conn)
        tx = self.conn.execute("SELECT id FROM finances WHERE flagged=1 ORDER BY anomaly_score DESC LIMIT 1").fetchone()[0]
        ex = ml.explain_anomaly(self.conn, tx)
        self.assertTrue(ex["reasons"]); self.assertEqual(len(ex["contributions"]), 5)

    def test_TC10_assistant_finds_relevant_document(self):
        r = knowledge.search(self.conn, "How soon must offerings be deposited in the bank?")
        self.assertEqual(r[0]["title"], "Financial Accountability Policy")

    def test_TC11_assistant_refuses_unrelated_question(self):
        self.assertEqual(knowledge.search(self.conn, "football transfer news"), [])

    def test_TC12_passwords_are_hashed(self):
        h = self.conn.execute("SELECT password_hash FROM users WHERE username=?", (GROUP_USER,)).fetchone()[0]
        self.assertNotIn(GROUP_PASS, h)


class SystemTests(Base):
    def setUp(self):
        self.c = appmod.app.test_client()

    def test_TC13_login_with_group_account(self):
        r = login(self.c); self.assertEqual(r.status_code, 302); self.assertTrue(r.headers["Location"].endswith("/dashboard"))

    def test_TC14_wrong_password_rejected(self):
        r = login(self.c, p="wrong"); self.assertIn(b"Wrong username or password", r.data)

    def test_TC15_pages_need_login(self):
        for u in ["/dashboard", "/finance", "/predict", "/governance"]:
            self.assertTrue(self.c.get(u).headers["Location"].endswith("/login"))

    def test_TC16_finance_role_cannot_open_attendance_prediction(self):
        login(self.c, "finance.officer", "Finance@2026")
        r = self.c.get("/predict", follow_redirects=True); self.assertIn(b"not allowed", r.data)

    def test_TC17_leader_role_cannot_open_finance(self):
        login(self.c, "branch.leader", "Leader@2026")
        r = self.c.get("/finance", follow_redirects=True); self.assertIn(b"not allowed", r.data)

    def test_TC18_all_pages_open_for_admin(self):
        login(self.c)
        for u in ["/dashboard", "/branches", "/manage/members", "/manage/ministries", "/manage/events", "/manage/outreach", "/manage/resources",
                  "/attendance", "/predict", "/finance", "/anomalies", "/assistant", "/governance", "/reports"]:
            self.assertEqual(self.c.get(u).status_code, 200, u)

    def test_TC19_add_member(self):
        login(self.c); n0 = self.conn.execute("SELECT COUNT(*) FROM members").fetchone()[0]
        self.c.post("/manage/members", data=dict(full_name="Test Member Kamara", gender="Male", age_group="Adults", branch_id="1", ministry_id="", phone="", join_date="2026-10-06", status="Active"))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM members").fetchone()[0], n0 + 1)

    def test_TC20_member_form_rejects_empty_name(self):
        login(self.c); n0 = self.conn.execute("SELECT COUNT(*) FROM members").fetchone()[0]
        self.c.post("/manage/members", data=dict(full_name="", gender="Male", age_group="Adults", branch_id="1", join_date="2026-10-06", status="Active"))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM members").fetchone()[0], n0)

    def test_TC21_add_attendance_and_reject_negative(self):
        login(self.c); n0 = self.conn.execute("SELECT COUNT(*) FROM attendance").fetchone()[0]
        self.c.post("/attendance", data=dict(branch_id="2", service_date="2026-10-11", service_type="Sunday Service", attendance="-5"))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM attendance").fetchone()[0], n0)
        self.c.post("/attendance", data=dict(branch_id="2", service_date="2026-10-11", service_type="Sunday Service", attendance="188"))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM attendance").fetchone()[0], n0 + 1)

    def test_TC22_finance_rejects_bad_amount(self):
        login(self.c); n0 = self.conn.execute("SELECT COUNT(*) FROM finances").fetchone()[0]
        self.c.post("/finance", data=dict(branch_id="1", tx_date="2026-10-05", category="Tithes", amount="abc"))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM finances").fetchone()[0], n0)

    def test_TC23_prediction_page_shows_result_and_reasons(self):
        login(self.c); r = self.c.post("/predict", data=dict(branch_id="3", service_date="2026-10-18", service_type="Sunday Service"))
        self.assertIn(b"people expected", r.data); self.assertIn(b"Why did the system predict this", r.data)

    def test_TC24_human_review_decision_saved(self):
        login(self.c); self.c.post("/anomalies")
        tx = self.conn.execute("SELECT id FROM finances WHERE flagged=1 LIMIT 1").fetchone()[0]
        self.c.post(f"/anomalies/{tx}/review", data=dict(status="Reviewed - genuine"))
        self.assertEqual(self.conn.execute("SELECT review_status FROM finances WHERE id=?", (tx,)).fetchone()[0], "Reviewed - genuine")

    def test_TC25_csv_export_and_role_limit(self):
        login(self.c); r = self.c.get("/reports/attendance.csv"); self.assertEqual(r.mimetype, "text/csv")
        c2 = appmod.app.test_client(); login(c2, "branch.leader", "Leader@2026")
        self.assertEqual(c2.get("/reports/income.csv").status_code, 403)

    def test_TC26_audit_log_records_login(self):
        login(self.c)
        n = self.conn.execute("SELECT COUNT(*) FROM audit_log WHERE action='LOGIN' AND username=?", (GROUP_USER,)).fetchone()[0]
        self.assertGreaterEqual(n, 1)

    def test_TC27_event_plan_page(self):
        login(self.c); eid = self.conn.execute("SELECT id FROM events WHERE status='Planned' LIMIT 1").fetchone()[0]
        self.assertIn(b"Recommended arrangements", self.c.get(f"/events/{eid}/plan").data)

    def test_TC28_assistant_cites_source_and_refuses_unknown(self):
        login(self.c)
        self.assertIn(b"Source: Financial Accountability Policy", self.c.post("/assistant", data=dict(question="deposit money in bank")).data)
        self.assertIn(b"No answer was found", self.c.post("/assistant", data=dict(question="football transfer news")).data)


if __name__ == "__main__":
    unittest.main(verbosity=2)
