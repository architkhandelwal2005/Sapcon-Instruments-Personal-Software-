from datetime import date
from typing import Optional

from dateutil.relativedelta import relativedelta

from app.extraction.schema import WEEKDAYS, RelativeDue

_KWARG_BY_UNIT = {"day": "days", "week": "weeks", "month": "months"}


def resolve_due_date(meeting_date: date, relative_due: Optional[RelativeDue]) -> Optional[date]:
    """A named day means the next one after the meeting - "Monday" said on a
    Friday is the 3 days away, and saying it on a Monday means the Monday after.
    An offset is plain arithmetic. Neither given (the model had no timeframe to
    work with) leaves the task undated rather than inventing a date."""
    if relative_due is None:
        return None
    if relative_due.weekday is not None:
        target = WEEKDAYS.index(relative_due.weekday)
        ahead = (target - meeting_date.weekday()) % 7 or 7
        return meeting_date + relativedelta(days=ahead)
    if relative_due.amount is None or relative_due.unit is None:
        return None
    return meeting_date + relativedelta(**{_KWARG_BY_UNIT[relative_due.unit]: relative_due.amount})
