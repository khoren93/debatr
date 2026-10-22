"""Mail from the site (`MAIL_FROM`, replies to `MAIL_REPLY_TO`) through the SMTP relay of the
sending service (`MAIL_SMTP_*`; Resend in production). Plain SMTP on purpose: another service
(Cloudflare Email Sending, Amazon SES, Brevo) is a change of settings, not of code.

Without a relay nothing is sent and the message is logged (development, tests); in production
only the recipient and the subject are, never the body: it carries one-time links.
"""

import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formatdate, make_msgid, parseaddr
from html import escape

from app.core.config import settings

logger = logging.getLogger(__name__)

SMTP_TIMEOUT_SECONDS = 15
ACCENT = "#D9FF3D"
INK = "#0A0B0F"


def enabled() -> bool:
    return bool(settings.MAIL_SMTP_HOST and settings.MAIL_SMTP_PASSWORD)


def _domain(address: str) -> str:
    return parseaddr(address)[1].rpartition("@")[2] or "localhost"


def build_message(to: str, subject: str, text: str, html: str) -> EmailMessage:
    message = EmailMessage()
    message["From"] = settings.MAIL_FROM
    message["To"] = to
    message["Subject"] = subject
    if settings.MAIL_REPLY_TO:
        message["Reply-To"] = settings.MAIL_REPLY_TO
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


def send(message: EmailMessage) -> bool:
    """Send now (blocking; the API calls it in a background task after the response). Never
    raises: a failure is logged and the caller goes on."""
    to, subject = str(message["To"]), str(message["Subject"])
    if not enabled():
        if settings.is_production:
            logger.warning("Mail to %s not sent (no MAIL_SMTP_HOST / PASSWORD): %s", to, subject)
        else:
            body = message.get_body(("plain",))
            content = body.get_content() if body is not None else ""
            logger.info("Mail to %s (not sent, no relay): %s\n%s", to, subject, content)
        return False
    host, port = settings.MAIL_SMTP_HOST, settings.MAIL_SMTP_PORT
    context = ssl.create_default_context()
    try:
        if port == 465:
            with smtplib.SMTP_SSL(
                host, port, timeout=SMTP_TIMEOUT_SECONDS, context=context
            ) as smtp:
                smtp.login(settings.MAIL_SMTP_USER, settings.MAIL_SMTP_PASSWORD or "")
                smtp.send_message(message)
        else:
            with smtplib.SMTP(host, port, timeout=SMTP_TIMEOUT_SECONDS) as smtp:
                smtp.starttls(context=context)
                smtp.login(settings.MAIL_SMTP_USER, settings.MAIL_SMTP_PASSWORD or "")
                smtp.send_message(message)
    except (OSError, smtplib.SMTPException) as e:
        logger.warning("Mail to %s failed (%s): %s", to, type(e).__name__, e)
        return False
    logger.info("Mail sent to %s: %s", to, subject)
    return True
