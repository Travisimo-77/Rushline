"""Owner tool: change an account's plan (billing checkout isn't built yet).
Usage:  python set_plan.py agency            (all accounts)
        python set_plan.py pro you@email.com (one account)"""
import sys

from app import db
from app.config import PLANS

plan = sys.argv[1] if len(sys.argv) > 1 else "agency"
if plan not in PLANS:
    sys.exit(f"Plan must be one of: {', '.join(PLANS)}")
if len(sys.argv) > 2:
    n = db.execute("UPDATE users SET plan=? WHERE email=?", plan, sys.argv[2].strip().lower())
else:
    n = db.execute("UPDATE users SET plan=?", plan)
print(f"Updated {n} account(s) to the {plan} plan. Refresh the app to see it.")
