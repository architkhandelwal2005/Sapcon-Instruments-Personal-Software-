"""The "here's what I understood" reply sent back after a voice note.

The owner is on the road; the phone is the only place he will ever check this
system's work. A reply of bare counts ("Logged - 3 people/companies, 2 tasks")
cannot show him the one mistake that matters: that a name was **linked to an
existing record** rather than filed as someone new. A wrong link fuses two
customers' histories and nothing else surfaces it.

So every linked name is marked, and the name as heard is shown next to the
record it was linked to whenever the two differ - that difference is the signal.
An uncertain or possible-duplicate entity is marked the same way. Names that are
our own staff are routine: 29 known people resolving correctly is not news.

WhatsApp accepts 4096 characters. A long meeting is trimmed by dropping detail
in order of how little it costs the reader - but never the marked lines, and
never the link, which is the only way to fix anything.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from app.entity_resolution.resolve import ResolutionResult
from app.minutes.generate import MeetingMinutesData, TaskRow

SOFT_LIMIT = 1500   # comfortable to read on a phone
HARD_LIMIT = 4000   # WhatsApp's own cap is 4096; leave headroom

_RISK = "! "
_PLAIN = "  "


@dataclass
class _Section:
    title: Optional[str]
    lines: list[str] = field(default_factory=list)

    def render(self) -> list[str]:
        if not self.lines:
            return []
        return ([self.title] if self.title else []) + self.lines


def meeting_readback_reply(
    data: MeetingMinutesData,
    resolutions: list[ResolutionResult],
    url: str,
    *,
    soft_limit: int = SOFT_LIMIT,
    hard_limit: int = HARD_LIMIT,
) -> str:
    """What was understood and what was recorded, small enough to read on a
    phone. Everything here comes from rows just written or decisions just made -
    nothing is re-derived or guessed."""
    risky, routine = _entity_lines(resolutions)
    summary = (data.summary or "").strip()

    return _fit(
        header=_header(data),
        summary=summary,
        risky=risky,
        routine=routine,
        tasks=[_task_line(t) for t in data.tasks],
        decisions=[f"- {d.description}" for d in data.decisions],
        url=url,
        soft_limit=soft_limit,
        hard_limit=hard_limit,
    )


def _header(data: MeetingMinutesData) -> str:
    kind = "Internal meeting" if data.kind == "internal" else "Logged"
    when = data.meeting_date.strftime("%d %b") if isinstance(data.meeting_date, date) else str(data.meeting_date)
    who = data.primary_contact_name
    return f"{kind} {when}" + (f" - {who}" if who else "")


def _entity_lines(resolutions: list[ResolutionResult]) -> tuple[list[str], list[str]]:
    """(needs a look, routine). A LINK is the line to check: a duplicate can be
    merged later, a wrong link cannot be cleanly unpicked."""
    risky: list[str] = []
    routine: list[str] = []
    for r in resolutions:
        heard = (r.mentioned_name or r.canonical_name or "").strip()
        if r.outcome == "linked":
            same = heard.lower() == (r.canonical_name or "").lower()
            line = f"\"{heard}\" -> linked to {r.canonical_name}" if not same else f"{r.canonical_name} -> linked"
            if _is_staff(r):
                routine.append(f"{line} (our team)")
            else:
                risky.append(line)
        elif r.outcome == "uncertain_created":
            dup = f", may be the same as {r.possible_duplicate_of}" if r.possible_duplicate_of else ""
            risky.append(f"\"{heard}\" -> NEW{dup}")
        else:
            routine.append(f"{heard} -> new")
    return risky, routine


def _is_staff(r: ResolutionResult) -> bool:
    """Our own 29 people resolving correctly is not news worth his attention."""
    return r.entity_type == "employee"


def _task_line(t: TaskRow) -> str:
    owners = ", ".join(a["name"] for a in t.assignees) if t.assignees else "no owner"
    due = t.due_date.strftime("%d %b") if isinstance(t.due_date, date) else "no due date"
    return f"[ ] {t.description} -- {owners} -- {due}"


def _fit(
    *,
    header: str,
    summary: str,
    risky: list[str],
    routine: list[str],
    tasks: list[str],
    decisions: list[str],
    url: str,
    soft_limit: int,
    hard_limit: int,
) -> str:
    """Trim in order of what costs the reader least, and stop as soon as it
    fits. The marked lines and the link survive every rung."""
    summary_cap: Optional[int] = None
    collapse_decisions = False
    collapse_routine = False
    task_cap: Optional[int] = None
    collapse_risky = False

    for rung in range(6):
        text = _compose(
            header=header, summary=summary, summary_cap=summary_cap,
            risky=risky, collapse_risky=collapse_risky,
            routine=routine, collapse_routine=collapse_routine,
            tasks=tasks, task_cap=task_cap,
            decisions=decisions, collapse_decisions=collapse_decisions,
            url=url,
        )
        if len(text) <= soft_limit or (rung == 5 and len(text) <= hard_limit):
            # Collapsing a later section can free more room than the summary cut
            # that came before it. "What I heard" is the part worth the most to
            # a reader checking the system's work, so give the space back.
            return _restore_summary(
                text, limit=soft_limit if len(text) <= soft_limit else hard_limit,
                header=header, summary=summary, summary_cap=summary_cap,
                risky=risky, collapse_risky=collapse_risky,
                routine=routine, collapse_routine=collapse_routine,
                tasks=tasks, task_cap=task_cap,
                decisions=decisions, collapse_decisions=collapse_decisions,
                url=url,
            )
        if rung == 0:
            summary_cap = 200
        elif rung == 1:
            collapse_decisions = True
        elif rung == 2:
            summary_cap = 100
        elif rung == 3:
            collapse_routine = True
        elif rung == 4:
            task_cap = 3

    # Still too long: the marked lines become a counted notice rather than
    # disappearing, because "there is something to check" must survive.
    collapse_risky = True
    return _compose(
        header=header, summary=summary, summary_cap=100,
        risky=risky, collapse_risky=collapse_risky,
        routine=routine, collapse_routine=True,
        tasks=tasks, task_cap=3,
        decisions=decisions, collapse_decisions=True,
        url=url,
    )[:hard_limit - len(url) - 2].rstrip() + "\n" + url


def _restore_summary(fitted: str, *, limit: int, summary_cap: Optional[int], **parts) -> str:
    """Widen the summary back out as far as the remaining room allows."""
    for wider in (200, None):
        if summary_cap is None or (wider is not None and wider <= summary_cap):
            continue
        candidate = _compose(summary_cap=wider, **parts)
        if len(candidate) <= limit:
            return candidate
    return fitted


def _compose(
    *,
    header: str,
    summary: str,
    summary_cap: Optional[int],
    risky: list[str],
    collapse_risky: bool,
    routine: list[str],
    collapse_routine: bool,
    tasks: list[str],
    task_cap: Optional[int],
    decisions: list[str],
    collapse_decisions: bool,
    url: str,
) -> str:
    sections: list[_Section] = []

    if summary:
        sections.append(_Section("WHAT I HEARD", [_clip(summary, summary_cap)]))

    people: list[str] = []
    if collapse_risky and risky:
        people.append(f"{_RISK}{len(risky)} name(s) need checking - open the link")
    else:
        people += [f"{_RISK}{line}" for line in risky]
    if collapse_routine and routine:
        people.append(f"{_PLAIN}+{len(routine)} more recorded")
    else:
        people += [f"{_PLAIN}{line}" for line in routine]
    sections.append(_Section("PEOPLE / COMPANIES", people))

    shown = tasks if task_cap is None else tasks[:task_cap]
    task_lines = list(shown)
    if task_cap is not None and len(tasks) > task_cap:
        task_lines.append(f"+{len(tasks) - task_cap} more tasks")
    sections.append(_Section("TASKS", task_lines))

    if collapse_decisions and decisions:
        sections.append(_Section("DECISIONS", [f"{len(decisions)} decision(s) recorded"]))
    else:
        sections.append(_Section("DECISIONS", decisions))

    body: list[str] = [header]
    for section in sections:
        rendered = section.render()
        if rendered:
            body.append("")
            body.extend(rendered)

    body.append("")
    body.append("Reply to this message to ADD anything I missed.")
    body.append(url)
    return "\n".join(body)


def _clip(text: str, cap: Optional[int]) -> str:
    if cap is None or len(text) <= cap:
        return text
    cut = text[:cap]
    stop = max(cut.rfind(". "), cut.rfind("? "), cut.rfind("! "))
    if stop > cap // 2:
        return cut[: stop + 1]
    return cut.rsplit(" ", 1)[0] + "..."
