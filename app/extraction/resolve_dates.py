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


ASSUMED_WORKING_DAYS = 3


def assumed_due_date(meeting_date: date) -> date:
    """When nothing was said about timing: three working days on, Sundays off.

    A task with no date never becomes overdue, so it can sit unnoticed for
    ever. A visible guess - marked as assumed wherever it is shown - is a
    deadline someone can correct; no date at all is one nobody notices is
    missing."""
    day, left = meeting_date, ASSUMED_WORKING_DAYS
    while left:
        day += relativedelta(days=1)
        if day.weekday() != 6:
            left -= 1
    return day
