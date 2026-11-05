"""Backfill profile/proxy fields, then export accounts to CSV/JSON for the sheet.

Sheet columns (tab "acc reg"):
raw, mail, pass, mail kp, ip, status, full_name, birthday, address, city,
phone, gpm_profile_id, gpm_profile_name, state, last_error, created_at, activated_at
"""

from __future__ import annotations

import csv
import json
import re
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
    "ip",
    "status",
    "full_name",
    "birthday",
    "address",
    "city",
    "phone",
    "gpm_profile_id",
    "gpm_profile_name",
    "state",
    "last_error",
    "created_at",
    "activated_at",
]

_IP_RE = re.compile(r"ip='([0-9a-fA-F:.]+)'")


def _identity_for(session, account: Account) -> dict:
    step = (
        session.query(Step)
        .join(Run, Run.id == Step.run_id)
        .filter(Run.account_id == account.id, Step.name == "ONBOARDED", Step.status == "DONE")
        .order_by(Step.id.desc())
        .first()
    )
    identity = {}
    if step and step.meta:
        value = (step.meta.get("data") or {}).get("identity")
        if isinstance(value, dict):
            identity = value
    return identity


def _build_identity(account: Account) -> dict:
    from flows.identity import build_identity

    generated = build_identity(
        account_id=account.email,
        first_name=account.first_name,
        last_name=account.last_name,
        city_state=account.city or "Delray Beach, FL",
        zip_code=account.zip or "33444",
    )
    return {
        "gender": generated.gender,
        "birth_date": generated.birth_date.isoformat(),
        "street": generated.street,
        "city": generated.city,
        "state": generated.state,
        "zip": generated.zip,
    }


def _proxy_ip_for(session, account: Account) -> str:
    if account.proxy_ip:
        return account.proxy_ip
    for name in ("PROXY_BOUND", "PROVISIONING"):
        step = (
            session.query(Step)
            .join(Run, Run.id == Step.run_id)
            .filter(Run.account_id == account.id, Step.name == name, Step.status == "DONE")
            .order_by(Step.id.desc())
            .first()
        )
        if not step or not step.meta:
            continue
        data = step.meta.get("data") or {}
        if isinstance(data.get("proxy_ip"), str) and data["proxy_ip"]:
            return data["proxy_ip"]
        probe = data.get("proxy_probe")
        if isinstance(probe, str):
            match = _IP_RE.search(probe)
            if match:
                return match.group(1)
    return ""


def backfill(session) -> int:
    updated = 0
    for account in session.query(Account).all():
        changed = False
        identity = _identity_for(session, account) or _build_identity(account)

        # The account row is authoritative for city/state/ZIP (resolved from the proxy at
        # creation); step metadata may carry a different rotating mobile exit city.
        parts = (account.city or "").split(",")
        city = parts[0].strip() if parts else ""
        state = parts[-1].strip() if len(parts) > 1 else identity.get("state", "")
        if city:
            identity["city"] = city
            identity["state"] = state
            identity["zip"] = account.zip or identity.get("zip", "")

        if not account.gender and identity.get("gender"):
            account.gender = identity["gender"]
            changed = True
        if not account.birth_date and identity.get("birth_date"):
            account.birth_date = identity["birth_date"]
            changed = True
        expected_address = (
            f"{identity.get('street', '')}, {identity.get('city', '')}, "
            f"{identity.get('state', '')} {identity.get('zip', '')}"
        ).strip(", ")
        if identity.get("street") and account.address_line != expected_address:
            account.address_line = expected_address
            changed = True
        proxy_ip = _proxy_ip_for(session, account)
        if proxy_ip and not account.proxy_ip:
            account.proxy_ip = proxy_ip
            changed = True
        if changed:
            updated += 1
    return updated


def main() -> None:
    box = SecretBox()
    rows: list[dict] = []
    success_states = {"ACTIVE", "WARMING", "ONBOARDED"}
    with session_scope() as session:
        updated = backfill(session)
        accounts = (
            session.query(Account)
            .filter(Account.state.in_(tuple(success_states)))
            .order_by(Account.created_at)
            .all()
        )
        for account in accounts:
            password = ""
            if account.password_enc:
                try:
                    password = box.decrypt(account.password_enc)
                except Exception:
                    password = "<decrypt-failed>"
            profile = session.get(Profile, account.profile_id) if account.profile_id else None
            rows.append(
                {
                    "raw": f"{account.email}:{password}",
                    "mail": account.email,
                    "pass": password,
                    "mail kp": account.email_alias or "",
                    "ip": _proxy_ip_for(session, account),
                    "status": f"{account.state}{('/' + account.substate) if account.substate else ''}",
                    "full_name": f"{account.first_name} {account.last_name}".strip(),
                    "birthday": account.birth_date or "",
                    "address": account.address_line or "",
                    "city": account.city,
                    "phone": account.phone_e164 or "",
                    "gpm_profile_id": profile.gpm_profile_id if profile else "",
                    "gpm_profile_name": profile.name if profile else "",
                    "state": account.state,
                    "last_error": account.last_error_code or account.quarantine_reason or "",
                    "created_at": account.created_at.strftime("%Y-%m-%d %H:%M") if account.created_at else "",
                    "activated_at": account.activated_at.strftime("%Y-%m-%d %H:%M") if account.activated_at else "",
                }
            )
    (OUT / "accounts.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    with (OUT / "accounts.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    try:
        from core.batches import list_batches

        batch_rows = list_batches()
        batch_fields = [
            "name", "status", "source", "target", "accounts", "sessions_today",
            "actions_today", "trust_min", "trust_max", "next_actions", "next_due", "created_at",
        ]
        with (OUT / "batches.csv").open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=batch_fields)
            writer.writeheader()
            for item in batch_rows:
                writer.writerow({key: item.get(key) for key in batch_fields})
    except Exception as exc:  # noqa: BLE001 - export of accounts must not fail on batch report
        print(json.dumps({"batches_export_error": str(exc)[:160]}))

    print(json.dumps({"accounts": len(rows), "backfilled": updated, "fields": len(FIELDS)}))


if __name__ == "__main__":
    main()
