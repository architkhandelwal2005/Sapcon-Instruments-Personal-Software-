"""Every page template parses. A broken template only fails when somebody opens
that page, so this catches it before anyone does."""

import pytest

from app.web.templating import TEMPLATE_DIR, templates


@pytest.mark.parametrize("name", sorted(p.name for p in TEMPLATE_DIR.glob("*.html")))
def test_template_compiles(name):
    templates.env.get_template(name)
