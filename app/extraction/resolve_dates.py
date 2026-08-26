from datetime import date
from typing import Optional

from dateutil.relativedelta import relativedelta

from app.extraction.schema import RelativeDue

_KWARG_BY_UNIT = {"day": "days", "week": "weeks", "month": "months"}


def resolve_due_date(meeting_date: date, relative_due: Optional[RelativeDue]) -> Optional[date]:
    if relative_due is None:
        return None
    kwarg = _KWARG_BY_UNIT[relative_due.unit]
    return meeting_date + relativedelta(**{kwarg: relative_due.amount})
