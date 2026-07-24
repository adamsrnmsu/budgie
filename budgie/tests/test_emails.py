"""Email drafts: the pace sentence, and what `budgie emails` writes by default."""

import email
import email.policy
from datetime import date

from click.testing import CliRunner

from budgie.budgie import cli
from budgie.core.allocation import Allocation
from budgie.core.burndown import burndown
from budgie.emails import build_message, render_email, render_html_email

AS_OF = date(2026, 6, 30)


def _status(fte=0.25, spent=180.0):
    alloc = Allocation(
        name="Alice",
        fte=fte,
        hours_spent=spent,
        available_hours=1992.0,
        email="alice@example.com",
    )
    return burndown(alloc, 2026, as_of=AS_OF)


def _plain_part(msg):
    return msg.get_body(preferencelist=("plain",)).get_content()


def test_text_draft_states_the_weekly_commitment():
    draft = render_email(_status().allocation, 2026, pace=_status().required_pace)
    assert "hours a week" in draft.body
    assert "% of your time" in draft.body


def test_pace_is_omitted_when_not_supplied():
    # The pace is opt-in, so an allocation with no burn-down context renders
    # exactly as it always did.
    draft = render_email(_status().allocation, 2026)
    assert "a week" not in draft.body


def test_exhausted_allocation_says_so_instead_of_a_pace():
    draft = render_email(
        _status(spent=600).allocation, 2026, pace=_status(spent=600).required_pace
    )
    assert "no hours left" in draft.body


def test_html_body_carries_the_pace_row_and_sentence():
    html = render_html_email(_status(), 2026)
    assert "To finish on plan" in html
    assert "of your time" in html


def test_the_eml_text_part_carries_the_pace_too():
    # A recipient whose client blocks HTML must still get the whole message.
    msg = build_message(_status(), 2026)
    assert "hours a week" in _plain_part(msg)


def test_emails_writes_eml_and_charts_by_default(tmp_path):
    result = CliRunner().invoke(
        cli, ["emails", "--out-dir", str(tmp_path), "--as-of", "2026-06-30"]
    )

    assert result.exit_code == 0, result.output
    assert list(tmp_path.glob("*.eml")), "expected .eml drafts by default"
    assert list((tmp_path / "charts").glob("*.png")), "expected burn-down charts"


def test_plain_flag_still_writes_text_drafts(tmp_path):
    result = CliRunner().invoke(
        cli,
        ["emails", "--plain", "--out-dir", str(tmp_path), "--as-of", "2026-06-30"],
    )

    assert result.exit_code == 0, result.output
    assert list(tmp_path.glob("*.txt"))
    assert not list(tmp_path.glob("*.eml"))
    # Plain drafts get the pace as well. Alice has hours left; David is over
    # his allocation and gets the exhausted wording instead.
    assert "of your time" in (tmp_path / "alice.txt").read_text()
    assert "no hours left" in (tmp_path / "david.txt").read_text()


def test_preview_renders_in_html_mode(tmp_path):
    # The preview used to be silently skipped whenever --html was passed.
    result = CliRunner().invoke(
        cli, ["emails", "--out-dir", str(tmp_path), "--as-of", "2026-06-30"]
    )

    assert "Preview" in result.output
    assert "Subject:" in result.output


def test_eml_embeds_the_chart_by_content_id(tmp_path):
    CliRunner().invoke(
        cli, ["emails", "--out-dir", str(tmp_path), "--as-of", "2026-06-30"]
    )
    raw = next(tmp_path.glob("*.eml")).read_bytes()
    msg = email.message_from_bytes(raw, policy=email.policy.default)

    # Outlook won't render data: URIs, so the chart must be a cid: attachment.
    assert any(part.get_content_type() == "image/png" for part in msg.walk())
    assert "cid:burndown" in msg.get_body(preferencelist=("html",)).get_content()
