"""Settings for the CAC Explainable AI system. Change values here, not in other files."""
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "cac_xai.db")
SECRET_KEY = "cac-explainable-ai-prototype-secret"

# The four sites of the case study (name, short code, location)
BRANCHES = [
    ("Mission Headquarters", "HQ", "Freetown"),
    ("Kenema Branch", "KEN", "Kenema"),
    ("Kissy Road Branch", "KIS", "Kissy Road, Freetown"),
    ("Dwazark Branch", "DWZ", "Dwazark, Freetown"),
]

# Rules of thumb used by the Event Planner (the church can change these numbers)
PLAN_RATIOS = {
    "seat_buffer": 1.10,            # seats = predicted people x 1.10
    "attendees_per_volunteer": 25,  # one volunteer for every 25 people
    "food_portion_rate": 0.80,      # 80% of people are expected to eat
    "share_arriving_by_vehicle": 0.30,
    "people_per_vehicle": 3,
}

# Knowledge assistant: minimum similarity before an answer is shown
ASSISTANT_MIN_SCORE = 0.10
