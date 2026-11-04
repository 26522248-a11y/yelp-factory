"""Backfill account profile fields from ONBOARDED step metadata, then export CSV/JSON."""

from __future__ import annotations

import json
from pathlib import Path

from core.crypto import SecretBox
from db.models import Account, Profile, Run, Step
from db.session import session_scope

OUT = Path("data/accounts_export")
OUT.mkdir(parents=True, exist_ok=True)

FIELDS = [
    "raw",
    "mail",
    "pass",
    "mail kp",
    "status",
    "first_name",
    "last_name",
    "gender",
    "birthday",
    "address",
    "city",
    "zip",
    "phone",
    "gpm_profile_id",
    "gpm_profile_name",
    "yelp_user_id",
    "state",
    "substate",
    "last_error",
    "retry_count",
    "created_at",
    "activated_at",
    "account_id",
]


def backfill(session) -> int:
    from flows.identity import build_identity

    updated = 0
    accounts = session.query(Account).all()
    for acc in accounts:
        step = (
            session.query(Step)
            .join(Run, Run.id == Step.run_id)
            .filter(Run.account_id == acc.id, Step.name == "ONBOARDED", Step.status == "DONE")
            .order_by(Step.id.desc())
            .first()
        )
        identity = {}
        if step and step.meta:
            identity = (step.meta.get("data") or {}).get("identity") or {}
        if not isinstance(identity, dict) or not identity:
            # Identity is deterministic per account, so it can always be regenerated.
            identity = {
                "gender": None,
            }
            generated = build_identity(
                account_id=acc.email,
                first_name=acc.first_name,
                last_name=acc.last_name,
                city_state=acc.city or "Delray Beach, FL",
                zip_code=acc.zip or "33444",
            )
            identity = {
                "gender": generated.gender,
                "birth_date": generated.birth_date.isoformat(),
                "street": generated.street,
                "city": generated.city,
                "state": generated.state,
                "zip": generated.zip,
            }
        changed = False
        if not acc.gender and identity.get("gender"):
            acc.gender = identity["gender"]
            changed = True
        if not acc.birth_date and identity.get("birth_date"):
            acc.birth_date = identity["birth_date"]
            changed = True
        if not acc.address_line and identity.get("street"):
            acc.address_line = f"{identity['street']}, {identity.get('city','')}, {identity.get('state','')} {identity.get('zip','')}".strip(", ")
            changed = True
        if changed:
            updated += 1
    return updated


def main() -> None:
    box = SecretBox()
    rows: list[dict] = []
    with session_scope() as session:
        updated = backfill(session)
        for acc in session.query(Account).order_by(Account.created_at).all():
            password = ""
            if acc.password_enc:
                try:
                    password = box.decrypt(acc.password_enc)
                except Exception:
                    password = "<decrypt-failed>"
            profile = session.get(Profile, acc.profile_id) if acc.profile_id else None
            rows.append(
                {
                    "raw": f"{acc.email}:{password}",
                    "mail": acc.email,
                    "pass": password,
                    "mail kp": acc.email_alias or "",
                    "status": f"{acc.state}{('/' + acc.substate) if acc.substate else ''}",
                    "first_name": acc.first_name,
                    "last_name": acc.last_name,
                    "gender": acc.gender or "",
                    "birthday": acc.birth_date or "",
                    "address": acc.address_line or "",
                    "city": acc.city,
                    "zip": acc.zip,
                    "phone": acc.phone_e164 or "",
                    "gpm_profile_id": profile.gpm_profile_id if profile else "",
                    "gpm_profile_name": profile.name if profile else "",
                    "yelp_user_id": acc.yelp_user_id or "",
                    "state": acc.state,
                    "substate": acc.substate or "",
                    "last_error": acc.last_error_code or acc.quarantine_reason or "",
                    "retry_count": acc.retry_count,
                    "created_at": acc.created_at.strftime("%Y-%m-%d %H:%M") if acc.created_at else "",
                    "activated_at": acc.activated_at.strftime("%Y-%m-%d %H:%M") if acc.activated_at else "",
                    "account_id": str(acc.id),
                }
            )
    (OUT / "accounts.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    import csv

    with (OUT / "accounts.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print(json.dumps({"accounts": len(rows), "backfilled": updated}))


if __name__ == "__main__":
    main()
