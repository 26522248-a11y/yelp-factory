"""E-17: a number already used by another account is never assigned twice."""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

from db.models import SMSNumber
from db.session import session_scope

pytestmark = pytest.mark.usefixtures("db_ready")


def test_E17_number_is_unique_in_the_pool(make_account):
    account = make_account()
    with session_scope() as session:
        session.add(SMSNumber(e164="+15125559999", area_code="512", provider="fake", used_by_account=account.id))
    with pytest.raises(IntegrityError):
        with session_scope() as session:
            session.add(SMSNumber(e164="+15125559999", area_code="512", provider="fake"))

    with session_scope() as session:
        rows = session.query(SMSNumber).filter(SMSNumber.used_by_account == account.id).all()
        assert len(rows) == 1
        session.query(SMSNumber).filter(SMSNumber.e164 == "+15125559999").delete()
