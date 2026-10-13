# CAC Sierra Leone - Explainable AI Framework (Final Year Project)

Design and Evaluation of an Explainable Artificial Intelligence Framework for Predicting Member Engagement
and Organisational Performance in Faith-Based Organisations.
Case study: Christ Apostolic Church Sierra Leone - Mission Headquarters, Kenema, Kissy Road and Dwazark.

University of Sierra Leone - Institute of Public Administration and Management (IPAM) - Department of Information Technology
Supervisor: Mr. Oluwatosin B. Ayorinde

Group members: Michael Kamara (Group Leader, DIP-16723), Joshua Saio Conteh (DIP-16698), Sallu Koroma (DIP-16160),
Mohamed Sandi (DIP-16655), Patrick Kawa (DIP-15991)

## What it does
* Attendance prediction with a plain-language explanation of WHY (Random Forest + Shapley values)
* Event planning: seats, volunteers, food portions and parking from the predicted attendance
* Income trends and 3-month forecast per branch, with explanation (Gradient Boosting + Shapley values)
* Unusual-transaction detection (Isolation Forest) - flags are for HUMAN review only
* Knowledge assistant that answers ONLY from approved church documents and names the source
* Multi-branch dashboard, outreach, resources, ministries, members, reports (CSV), model governance and audit log
* Role-based login (administrator, finance officer, branch leader)

## Run (Windows) - easiest
Double-click `SETUP_AND_RUN_WINDOWS.bat`, then open http://127.0.0.1:5000

## Run (manual, any computer)
```
python -m venv venv
venv\Scripts\activate          (Mac/Linux: source venv/bin/activate)
pip install -r requirements.txt
python app.py
```
Open http://127.0.0.1:5000

## Logins
| Role | Username | Password |
|---|---|---|
| Administrator (group account) | cac-explainable-ai | explainable_aigrp |
| Finance officer | finance.officer | Finance@2026 |
| Branch leader | branch.leader | Leader@2026 |

## Tests
```
python -m unittest tests.test_system -v
```
28 automated tests (TC01-TC28).

## Reset the sample data
Delete `cac_xai.db`, then run `python seed_data.py` (or just start the app - it recreates the file).

## Important notes
* All data is SYNTHETIC (made up for testing, as allowed in the proposal). It contains no real personal or financial information.
* Predictions and flags support human decision-making; the system never decides on members, money or policy.

## Files
`app.py` web pages and rules | `ml_engine.py` AI models + explanations | `knowledge.py` document search |
`db.py` database | `seed_data.py` sample data | `charts.py` charts | `templates/` pages | `static/` styles | `tests/` tests
