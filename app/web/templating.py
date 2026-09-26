"""One Jinja environment for the whole app.

Every route module used to build its own, which meant the signed-in person had
to be passed into each template call by hand - and any route that forgot would
silently render a page with no name and no sign-out link. A context processor
puts the actor on every render instead, so forgetting is not possible.
"""

from pathlib import Path

from fastapi import Request
from fastapi.templating import Jinja2Templates

TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"


def _actor(request: Request) -> dict:
    """None on the login and enrol pages, which render before anyone is known."""
    return {"actor": getattr(request.state, "actor", None)}


templates = Jinja2Templates(directory=str(TEMPLATE_DIR), context_processors=[_actor])
