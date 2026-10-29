import re

import pytest

from marketplace.paths import DASHBOARD_DIR

HTML = DASHBOARD_DIR / "index.html"


@pytest.mark.skipif(not HTML.exists(), reason="run `make dashboard` first")
def test_dashboard_self_contained_with_all_pages():
    html = HTML.read_text()
    assert not re.search(r"<script[^>]+src=[\"']https?://", html), "external script found"
    assert not re.search(r"<link[^>]+href=[\"']https?://", html), "external stylesheet found"
    for page in ("exec", "growth", "customers", "delivery", "sellers", "rca"):
        assert f'["{page}"' in html
    assert "window.DATA" in html
