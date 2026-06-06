"""Send user feedback by email via SMTP.

Configuration is read from environment / Streamlit secrets:
  SMTP_HOST, SMTP_PORT (default 587), SMTP_USER, SMTP_PASSWORD, SMTP_FROM
The recipient is fixed below and is never surfaced in the UI.
"""

import os
import smtplib
import ssl
from email.message import EmailMessage

# Recipient for all feedback. Intentionally kept server-side, never shown in UI.
_FEEDBACK_TO = "baijiuyang@hotmail.com"


class FeedbackError(Exception):
    """Raised when feedback cannot be sent."""


def feedback_configured() -> bool:
    """True if the SMTP settings needed to send feedback are present."""
    return all(os.environ.get(k) for k in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD"))


def send_feedback(message: str, contact: str = "") -> None:
    """Email a feedback message. `contact` is an optional reply-to address."""
    message = (message or "").strip()
    if not message:
        raise FeedbackError("Feedback message is empty.")

    host = os.environ.get("SMTP_HOST")
    user = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASSWORD")
    if not (host and user and password):
        raise FeedbackError("Feedback email is not configured on the server.")

    port = int(os.environ.get("SMTP_PORT", "587"))
    sender = os.environ.get("SMTP_FROM", user)
    contact = contact.strip()

    msg = EmailMessage()
    msg["Subject"] = "Dual Caption feedback"
    msg["From"] = sender
    msg["To"] = _FEEDBACK_TO
    if contact:
        msg["Reply-To"] = contact
    body = message + (f"\n\n— from: {contact}" if contact else "")
    msg.set_content(body)

    ctx = ssl.create_default_context()
    try:
        if port == 465:
            with smtplib.SMTP_SSL(host, port, context=ctx, timeout=30) as s:
                s.login(user, password)
                s.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=30) as s:
                s.starttls(context=ctx)
                s.login(user, password)
                s.send_message(msg)
    except FeedbackError:
        raise
    except Exception as e:  # smtplib/ssl/socket errors
        raise FeedbackError(f"Could not send feedback: {e}") from e
