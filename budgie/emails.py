"""
Personalized hours-remaining emails.

Turns each :class:`budgie.core.allocation.Allocation` into a per-person email
draft. This module only *renders* drafts (and can write them to files) -- it
never sends anything. Sending is an outward action left to a reviewed,
explicit step (e.g. importing the drafts into a mail client).
"""

from __future__ import annotations

from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path

from budgie.core.allocation import Allocation
from budgie.core.burndown import BurndownStatus

# Content-ID used to reference the embedded burn-down chart from the HTML body.
CHART_CID = "burndown"

# Outlook renders HTML through Word: table layout + inline styles only, and it
# will NOT display base64 data: URIs -- hence the cid: attachment below.
_FONT = "Arial, Helvetica, sans-serif"
_MONO = "Consolas, 'Courier New', monospace"
_INK = "#16211c"
_MUTED = "#5d6b62"
_LINE = "#dde5df"
_GREEN = "#2f8f5b"
_AMBER = "#b26a00"
_RED = "#c0362c"

DEFAULT_SUBJECT = "Your {year} hours: {remaining:,.0f} remaining"

DEFAULT_BODY = """\
Hi {name},

Here's where your {year} time allocation stands:

  FTE allocation:   {fte:.2f}
  Hours allocated:  {allocated:,.0f}
  Hours spent:      {spent:,.0f}
  Hours remaining:  {remaining:,.0f}  ({pct_used:.0%} used)
{status_line}
Please let me know if anything looks off.

Thanks,
Budgie
"""


@dataclass(frozen=True)
class EmailDraft:
    to: str | None
    subject: str
    body: str

    def as_text(self) -> str:
        """Render as a simple RFC-822-ish text block for a draft file."""
        to = self.to or "(no email on file)"
        return f"To: {to}\nSubject: {self.subject}\n\n{self.body}"


def _status_line(alloc: Allocation) -> str:
    if alloc.is_over_budget:
        return (
            f"\n⚠ You are OVER your allocation by "
            f"{abs(alloc.hours_remaining):,.0f} hours.\n"
        )
    if alloc.fraction_used >= 0.9:
        return "\n⚠ You've used 90%+ of your allocation.\n"
    return ""


def render_email(
    alloc: Allocation,
    year: int,
    subject_template: str = DEFAULT_SUBJECT,
    body_template: str = DEFAULT_BODY,
) -> EmailDraft:
    """Render a personalized :class:`EmailDraft` for one allocation."""
    fields = {
        "name": alloc.name,
        "year": year,
        "fte": alloc.fte,
        "allocated": alloc.allocated_hours,
        "spent": alloc.hours_spent,
        "remaining": alloc.hours_remaining,
        "pct_used": alloc.fraction_used,
        "status_line": _status_line(alloc),
    }
    return EmailDraft(
        to=alloc.email,
        subject=subject_template.format(**fields),
        body=body_template.format(**fields),
    )


def write_drafts(
    allocations: list[Allocation],
    year: int,
    out_dir: str | Path,
) -> list[Path]:
    """Render and write one draft file per allocation; return the paths."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = []
    for alloc in allocations:
        draft = render_email(alloc, year)
        path = out / f"{slug(alloc.name)}.txt"
        path.write_text(draft.as_text())
        paths.append(path)
    return paths


def slug(name: str) -> str:
    return name.lower().replace(" ", "_")


# --------------------------------------------------------------------------
# Outlook-targeted HTML + .eml drafts
# --------------------------------------------------------------------------


def _pace_banner(status: BurndownStatus) -> tuple[str, str]:
    """(color, message) summarising whether they're on pace."""
    alloc = status.allocation
    if alloc.is_over_budget:
        return _RED, (
            f"You are over your allocation by {abs(alloc.hours_remaining):,.0f} hours."
        )
    if status.projected_over:
        when = status.exhaustion_date
        tail = f" and run out around {when:%B %-d}" if when else ""
        return _RED, (
            f"At your current pace you'll finish the year at "
            f"{status.projected_total:,.0f} hours{tail}."
        )
    if status.is_over_pace:
        return _AMBER, (
            f"You're {status.variance:,.0f} hours ahead of an even pace, but still "
            f"projected to land within your allocation."
        )
    return _GREEN, (
        f"You're {abs(status.variance):,.0f} hours behind an even pace -- comfortably "
        f"on track."
    )


def _row(label: str, value: str, *, bold: bool = False, color: str = _INK) -> str:
    weight = "bold" if bold else "normal"
    return (
        f"<tr>"
        f'<td style="padding:7px 0;border-bottom:1px solid {_LINE};color:{_MUTED};'
        f'font-family:{_FONT};font-size:14px;">{label}</td>'
        f'<td align="right" style="padding:7px 0;border-bottom:1px solid {_LINE};'
        f'color:{color};font-family:{_MONO};font-size:15px;font-weight:{weight};">'
        f"{value}</td>"
        f"</tr>"
    )


def render_html_email(status: BurndownStatus, year: int) -> str:
    """Render an Outlook-safe HTML body (tables + inline styles, cid: image)."""
    alloc = status.allocation
    color, message = _pace_banner(status)
    remaining_color = _RED if alloc.is_over_budget else _INK

    # Built up front so the template below holds only simple substitutions --
    # a formatter can't reflow call expressions it can't see.
    rows = "\n      ".join(
        [
            _row("FTE allocation", f"{alloc.fte:.2f}"),
            _row("Hours allocated", f"{alloc.allocated_hours:,.0f}"),
            _row("Hours spent", f"{alloc.hours_spent:,.0f}"),
            _row(
                "Hours remaining",
                f"{alloc.hours_remaining:,.0f}",
                bold=True,
                color=remaining_color,
            ),
            _row("Used", f"{alloc.fraction_used:.0%}"),
        ]
    )
    as_of = f"{status.as_of:%B %-d, %Y}"

    return f"""\
<html><body style="margin:0;padding:0;background:#f4f6f3;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" \
style="background:#f4f6f3;padding:24px 0;">
<tr><td align="center">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0" \
style="width:600px;max-width:600px;background:#ffffff;border:1px solid {_LINE};">
  <tr><td style="padding:24px 28px 8px 28px;">
    <div style="font-family:{_MONO};font-size:12px;letter-spacing:2px;\
text-transform:uppercase;color:{_GREEN};">Budgie</div>
    <div style="font-family:{_FONT};font-size:21px;font-weight:bold;color:{_INK};\
padding-top:6px;">Your {year} hours</div>
  </td></tr>

  <tr><td style="padding:12px 28px 0 28px;">
    <div style="font-family:{_FONT};font-size:15px;color:{_INK};">Hi {alloc.name},</div>
    <div style="font-family:{_FONT};font-size:15px;color:{_INK};padding-top:10px;">\
Here's where your time allocation stands as of {as_of}.</div>
  </td></tr>

  <tr><td style="padding:16px 28px 0 28px;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
      {rows}
    </table>
  </td></tr>

  <tr><td style="padding:18px 28px 0 28px;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
      <tr><td style="border-left:4px solid {color};padding:10px 14px;background:#fafbfa;\
font-family:{_FONT};font-size:14px;color:{_INK};line-height:1.5;">{message}</td></tr>
    </table>
  </td></tr>

  <tr><td style="padding:20px 28px 4px 28px;">
    <img src="cid:{CHART_CID}" width="544" alt="Hours burn-down chart" \
style="display:block;width:544px;max-width:100%;height:auto;border:0;">
  </td></tr>

  <tr><td style="padding:8px 28px 26px 28px;">
    <div style="font-family:{_FONT};font-size:13px;color:{_MUTED};line-height:1.5;">\
The dashed line is an even pace across the year; the dotted line projects your current \
rate to December. Let me know if anything looks off.</div>
    <div style="font-family:{_FONT};font-size:13px;color:{_INK};padding-top:14px;">\
Thanks,<br>Budgie</div>
  </td></tr>
</table>
</td></tr></table>
</body></html>"""


def build_message(
    status: BurndownStatus,
    year: int,
    chart_png: bytes | None = None,
) -> EmailMessage:
    """Build a multipart email (plain text + Outlook-safe HTML + inline chart).

    The chart is attached with a Content-ID and referenced as ``cid:`` from the
    HTML, because Outlook will not render base64 ``data:`` image URIs.
    """
    alloc = status.allocation
    draft = render_email(alloc, year)

    msg = EmailMessage()
    msg["Subject"] = draft.subject
    if alloc.email:
        msg["To"] = alloc.email
    msg.set_content(draft.body)  # text/plain fallback
    msg.add_alternative(render_html_email(status, year), subtype="html")

    if chart_png:
        # The HTML alternative becomes multipart/related once the image is added.
        html_part = msg.get_payload()[-1]
        html_part.add_related(
            chart_png, maintype="image", subtype="png", cid=f"<{CHART_CID}>"
        )
    return msg


def write_eml_drafts(
    statuses: list[BurndownStatus],
    year: int,
    out_dir: str | Path,
    charts: dict[str, bytes] | None = None,
) -> list[Path]:
    """Write one ``.eml`` per person (openable straight into Outlook).

    Drafts only -- nothing is sent.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    charts = charts or {}
    paths = []
    for status in statuses:
        name = status.allocation.name
        msg = build_message(status, year, charts.get(name))
        path = out / f"{slug(name)}.eml"
        path.write_bytes(msg.as_bytes())
        paths.append(path)
    return paths
