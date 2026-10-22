"""Mail from the site (`MAIL_FROM`, replies to `MAIL_REPLY_TO` or else `SUPPORT_EMAIL`) through
the SMTP relay of the sending service (`MAIL_SMTP_*`; Resend in production). Plain SMTP on
purpose: another service (Cloudflare Email Sending, Amazon SES, Brevo) is a change of settings,
not of code.

Without a relay nothing is sent and the message is logged (development, tests); in production
only the recipient and the subject are, never the body: it carries one-time links. `send` says
what became of a letter (`Outcome`, with the relay's answer); services/mail_log records it.
"""

import logging
import smtplib
import ssl
from collections.abc import Buffer
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formatdate, make_msgid, parseaddr
from html import escape
from typing import Literal

from app.core.config import settings

logger = logging.getLogger(__name__)

SMTP_TIMEOUT_SECONDS = 15
TLS_PORTS = (465, 2465)  # TLS from the first byte; the others start plain and ask STARTTLS
ACCENT = "#D9FF3D"
INK = "#0A0B0F"


def enabled() -> bool:
    return bool(settings.MAIL_SMTP_HOST and settings.MAIL_SMTP_PASSWORD and settings.MAIL_FROM)


def reply_to() -> str:
    return settings.MAIL_REPLY_TO or settings.SUPPORT_EMAIL


def _domain(address: str) -> str:
    return parseaddr(address)[1].rpartition("@")[2] or "localhost"


def build_message(to: str, subject: str, text: str, html: str) -> EmailMessage:
    message = EmailMessage()
    message["From"] = settings.MAIL_FROM
    message["To"] = to
    message["Subject"] = subject
    if reply_to():
        message["Reply-To"] = reply_to()
    message["Date"] = formatdate(localtime=False)
    message["Message-ID"] = make_msgid(domain=_domain(settings.MAIL_FROM))
    # Mail sent by the site, not by a person: no out-of-office replies to it.
    message["Auto-Submitted"] = "auto-generated"
    message.set_content(text)
    message.add_alternative(html, subtype="html")
    return message


def letter(*, title: str, lines: list[str], button: str, url: str, footer: str) -> tuple[str, str]:
    """The site's one-button letter: the plain text and the HTML of the same words (`lines` are
    paragraphs of plain text, escaped here)."""
    text = "\n\n".join([*lines, f"{button}: {url}", footer, f"— Debatr\n{settings.SITE_URL}"])
    paragraphs = "".join(
        f'<p style="margin:0 0 16px;font-size:15px;line-height:1.55;color:#33363f">{escape(line)}</p>'
        for line in lines
    )
    html = f"""<!doctype html>
<html><body style="margin:0;padding:24px 12px;background:#f3f4f7;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif">
<div style="max-width:520px;margin:0 auto;background:#ffffff;border-radius:16px;padding:32px 28px">
<div style="font-size:20px;font-weight:800;letter-spacing:-0.02em;color:{INK};margin:0 0 20px">Debatr</div>
<h1 style="font-size:22px;line-height:1.25;margin:0 0 16px;color:{INK}">{escape(title)}</h1>
{paragraphs}
<p style="margin:24px 0"><a href="{escape(url, quote=True)}" style="display:inline-block;background:{ACCENT};color:{INK};font-weight:700;font-size:15px;text-decoration:none;padding:12px 22px;border-radius:12px">{escape(button)}</a></p>
<p style="margin:0 0 16px;font-size:13px;line-height:1.5;color:#6b7080">If the button does not work, open this link:<br><a href="{escape(url, quote=True)}" style="color:#4a6fd8;word-break:break-all">{escape(url)}</a></p>
<p style="margin:24px 0 0;font-size:13px;line-height:1.5;color:#6b7080">{escape(footer)}</p>
</div>
<p style="max-width:520px;margin:16px auto 0;text-align:center;font-size:12px;color:#8b90a0"><a href="{escape(settings.SITE_URL, quote=True)}" style="color:#8b90a0">{escape(_domain(settings.MAIL_FROM))}</a></p>
</body></html>"""
    return text, html


@dataclass(frozen=True)
class Outcome:
    """What became of one letter: `sent` (the relay took it; `reply` = its answer, often with
    its id of the letter), `failed` (`error`) or `off` (no relay set up)."""

    status: Literal["sent", "failed", "off"]
    reply: str | None = None
    error: str | None = None


def _decode(value: bytes | str) -> str:
    return value.decode("utf-8", "replace") if isinstance(value, bytes) else str(value)


class _Relay(smtplib.SMTP):
    """Keeps the relay's answer to the letter itself (smtplib drops it)."""

    reply = ""

    def data(self, msg: Buffer | str) -> tuple[int, bytes]:
        code, text = super().data(msg)
        self.reply = f"{code} {_decode(text)}"
        return code, text


class _TLSRelay(smtplib.SMTP_SSL):
    reply = ""

    def data(self, msg: Buffer | str) -> tuple[int, bytes]:
        code, text = super().data(msg)
        self.reply = f"{code} {_decode(text)}"
        return code, text


def error_text(e: Exception) -> str:
    """An SMTP failure in words (the relay's code and answer when it gave one)."""
    if isinstance(e, smtplib.SMTPResponseException):
        detail = f"{e.smtp_code} {_decode(e.smtp_error)}"
    elif isinstance(e, smtplib.SMTPRecipientsRefused):
        detail = "; ".join(
            f"{to}: {code} {_decode(text)}" for to, (code, text) in e.recipients.items()
        )
    else:
        detail = str(e) or "no details"
    return f"{type(e).__name__}: {detail}"[:500]


def unreachable_hint(host: str, port: int, e: OSError) -> str:
    """Where the connection failed, and the usual reason a relay times out: the server's host
    drops outgoing mail ports (Hetzner Cloud blocks 25 and 465; 587 stays open)."""
    where = f"{host}:{port}"
    if isinstance(e, TimeoutError) and port in (25, 465):
        return f"{where}: hosts often block outgoing port {port}, set MAIL_SMTP_PORT=587"
    return where


def send(message: EmailMessage) -> Outcome:
    """Send now (blocking: the API runs it in a thread after its response). Never raises: a
    failure is logged and returned."""
    to, subject = str(message["To"]), str(message["Subject"])
    if not enabled():
        if settings.is_production:
            logger.warning("Mail to %s not sent (no relay or MAIL_FROM): %s", to, subject)
        else:
            body = message.get_body(("plain",))
            content = body.get_content() if body is not None else ""
            logger.info("Mail to %s (not sent, no relay): %s\n%s", to, subject, content)
        return Outcome("off", error="No relay: MAIL_SMTP_HOST, _PASSWORD or MAIL_FROM is not set")
    host, port = settings.MAIL_SMTP_HOST, settings.MAIL_SMTP_PORT
    context = ssl.create_default_context()
    try:
        if port in TLS_PORTS:
            with _TLSRelay(host, port, timeout=SMTP_TIMEOUT_SECONDS, context=context) as smtp:
                smtp.login(settings.MAIL_SMTP_USER, settings.MAIL_SMTP_PASSWORD or "")
                smtp.send_message(message)
                reply = smtp.reply
        else:
            with _Relay(host, port, timeout=SMTP_TIMEOUT_SECONDS) as smtp:
                smtp.starttls(context=context)
                smtp.login(settings.MAIL_SMTP_USER, settings.MAIL_SMTP_PASSWORD or "")
                smtp.send_message(message)
                reply = smtp.reply
    except (OSError, smtplib.SMTPException) as e:
        error = error_text(e)
        if not isinstance(e, smtplib.SMTPException):  # no answer from the relay at all
            error = f"{error} ({unreachable_hint(host, port, e)})"[:500]
        logger.warning("Mail to %s failed: %s", to, error)
        return Outcome("failed", error=error)
    logger.info("Mail sent to %s: %s (%s)", to, subject, reply)
    return Outcome("sent", reply=reply[:500] or None)
