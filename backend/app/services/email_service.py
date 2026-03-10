"""
Email service — AWS SES integration.

Renders the Jinja2 HTML monthly report email and delivers it via SES.
Both HTML and plain-text fallback bodies are sent.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import boto3
import structlog
from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.config import settings

logger = structlog.get_logger(__name__)

_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
_jinja_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=select_autoescape(["html"]),
)


def _get_ses_client():
    return boto3.client(
        "ses",
        region_name=settings.aws_region,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
    )


async def send_monthly_report_email(
    to_email: str,
    user_name: str | None,
    month_name: str,
    overview: dict,
    by_category: list[dict],
    health_score: int,
    download_url: str | None = None,
) -> None:
    """
    Send the monthly financial report to one user via AWS SES.

    Renders the HTML template and sends with a plain-text fallback.
    Raises on SES delivery failure so the caller can handle retries.
    """
    display_name = user_name or to_email.split("@")[0].title()

    # Render HTML body
    template = _jinja_env.get_template("email/monthly_report.html")
    html_body = template.render(
        user_name=display_name,
        month_name=month_name,
        overview=overview,
        by_category=by_category[:8],
        health_score=health_score,
        download_url=download_url,
        frontend_url=settings.frontend_url,
    )

    # Plain-text fallback
    net = overview.get("net", overview["income"] - overview["expenses"])
    text_body = (
        f"Hi {display_name},\n\n"
        f"Your {month_name} Financial Report is ready.\n\n"
        f"Income:        ${overview['income']:,.2f}\n"
        f"Expenses:      ${overview['expenses']:,.2f}\n"
        f"Net Savings:   ${net:,.2f}\n"
        f"Savings Rate:  {overview['savings_rate'] * 100:.1f}%\n"
        f"Health Score:  {health_score}/100\n\n"
    )
    if download_url:
        text_body += f"View your full report: {download_url}\n\n"
    text_body += f"Go to your dashboard: {settings.frontend_url}/dashboard\n"

    subject = f"Your {month_name} Financial Report"
    sender = f"{settings.ses_sender_name} <{settings.ses_sender_email}>"

    client = _get_ses_client()
    loop = asyncio.get_event_loop()

    def _send() -> None:
        client.send_email(
            Source=sender,
            Destination={"ToAddresses": [to_email]},
            Message={
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body": {
                    "Html": {"Data": html_body, "Charset": "UTF-8"},
                    "Text": {"Data": text_body, "Charset": "UTF-8"},
                },
            },
        )

    await loop.run_in_executor(None, _send)
    logger.info(
        "Monthly report email sent via SES",
        to=to_email,
        month=month_name,
        health_score=health_score,
    )
