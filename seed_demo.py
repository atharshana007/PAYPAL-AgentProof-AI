"""Reset the local demo database and seed a signed accessories mandate."""

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

import auditlog
import mandate


def main():
    database_path = Path(
        os.getenv("DB_PATH", str(auditlog.DEFAULT_DB_PATH))
    )
    expires_at = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
    demo_mandate = {
        "user": "Demo User",
        "max_total": 50,
        "allowed_categories": ["accessories"],
        "allowed_merchants": ["Demo Accessories Shop"],
        "expires_at": expires_at,
    }

    try:
        mandate.sign_mandate(demo_mandate)
    except ValueError as exc:
        print(f"Cannot seed demo: {exc}")
        return 1

    print(f"This will permanently reset the demo database: {database_path.resolve()}")
    if input("Type RESET to continue: ").strip() != "RESET":
        print("Reset cancelled; the database was not changed.")
        return 1

    if database_path.exists():
        database_path.unlink()
    auditlog.init_db()
    signed = mandate.create_and_store(demo_mandate)

    print("Demo database reset and signed mandate created.")
    print(f"Mandate signature: {signed['signature']}")
    print("Next steps:")
    print("1. Start the server with: .\\run.ps1")
    print("2. Open http://127.0.0.1:8765 and review the mandate.")
    print("3. Run the agent or try Rogue Agent to see policy decisions.")
    print("4. Review the audit log and verify its hash chain.")
    print("5. Open a dispute report from an audit event.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
