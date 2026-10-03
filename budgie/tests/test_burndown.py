import email
import email.policy
from datetime import date

from budgie.core.allocation import Allocation
from budgie.core.burndown import burndown
from budgie.core.calendar import year_span
from budgie.emails import CHART_CID, build_message, render_html_email, write_eml_drafts


def _alloc(spent, fte=0.5):
    return Allocation(
        name="Bob",
        fte=fte,
        hours_spent=spent,
        available_hours=1992,
        email="bob@example.com",
    )


def test_elapsed_and_expected_at_midyear():
    st = burndown(
        _alloc(0), year_span(2026), as_of=date(2026, 7, 2)
    )  # 183rd day of 365
    assert st.days_in_year == 365
    assert 0.49 < st.elapsed_fraction < 0.51
    # 0.5 FTE of 1992 = 996 allocated; roughly half by mid-year.
    assert 480 < st.expected_by_now < 515


def test_over_pace_and_exhaustion_date():
    st = burndown(_alloc(760), year_span(2026), as_of=date(2026, 7, 23))
    assert st.is_over_pace
    assert st.variance > 0
    assert st.projected_over
    # Burning ~3.6 h/day against 996 allocated -> runs dry in the autumn.
    assert st.exhaustion_date is not None
    assert st.exhaustion_date.year == 2026


def test_under_pace_has_no_exhaustion():
    st = burndown(_alloc(180, fte=0.25), year_span(2026), as_of=date(2026, 7, 23))
    assert not st.is_over_pace
    assert not st.projected_over
    assert st.exhaustion_date is None


def test_zero_spend_has_no_burn_rate():
    st = burndown(_alloc(0), year_span(2026), as_of=date(2026, 7, 23))
    assert st.burn_rate_per_day == 0
    assert st.exhaustion_date is None


def test_as_of_clamped_into_year():
    st = burndown(_alloc(100), year_span(2026), as_of=date(2030, 5, 1))
    assert st.as_of == date(2026, 12, 31)


def test_html_is_outlook_safe_and_references_cid():
    st = burndown(_alloc(760), year_span(2026), as_of=date(2026, 7, 23))
    html = render_html_email(st, 2026)
    assert f"cid:{CHART_CID}" in html
    # Outlook needs table layout + inline styles, never flex/grid or data: images.
    assert "<table" in html
    assert "display:flex" not in html
    assert "data:image" not in html


def test_eml_has_related_image_with_content_id(tmp_path):
    st = burndown(_alloc(760), year_span(2026), as_of=date(2026, 7, 23))
    msg = build_message(st, 2026, chart_png=b"\x89PNG\r\n\x1a\n fake")
    types = [p.get_content_type() for p in msg.walk()]
    assert "multipart/related" in types
    assert "text/plain" in types
    assert "image/png" in types

    paths = write_eml_drafts([st], 2026, tmp_path, charts={"Bob": b"\x89PNG fake"})
    assert paths[0].suffix == ".eml"
    parsed = email.message_from_bytes(
        paths[0].read_bytes(), policy=email.policy.default
    )
    assert parsed["To"] == "bob@example.com"
    cids = [p.get("Content-ID") for p in parsed.walk() if p.get("Content-ID")]
    assert f"<{CHART_CID}>" in cids
