import os, ssl, smtplib, socket
import logging
from typing import List, Optional, Tuple
from email.utils import formataddr, parseaddr, formatdate, make_msgid
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders

LOG = logging.getLogger(__name__)

def _get(name: str, default=None):
    try:
        import streamlit as st
        val = st.secrets.get(name, None)
        if val is not None:
            return val
    except Exception:
        pass
    return os.environ.get(name, default)

def _to_bool(v, default=False):
    if v is None: return default
    return str(v).strip().lower() in {"1","true","yes","y","on"}

def _normalize(addr: str) -> str:
    name, email = parseaddr(addr or "")
    return formataddr(((name or "").strip(), (email or "").strip())) if email else ""

def _build(subject, sender, to_addrs, html, text=None, reply_to=None,
           attachments: Optional[List[Tuple[str, bytes, str]]]=None):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = _normalize(sender)
    msg["To"] = ", ".join(_normalize(a) for a in to_addrs)
    if reply_to: msg["Reply-To"] = _normalize(reply_to)
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid()
    part1 = MIMEText(text or "Este correo contiene contenido HTML.", "plain", "utf-8")
    part2 = MIMEText(html or "", "html", "utf-8")
    msg.attach(part1); msg.attach(part2)
    for att in (attachments or []):
        filename, content, mime_type = att
        maintype, subtype = (mime_type.split("/", 1) + ["octet-stream"])[:2]
        part = MIMEBase(maintype, subtype)
        part.set_payload(content); encoders.encode_base64(part)
        part.add_header("Content-Disposition", f'attachment; filename="{filename}"')
        msg.attach(part)
    return msg

def _open():
    host = _get("SMTP_HOST")
    port = int(_get("SMTP_PORT", 587))
    user = _get("SMTP_USER")
    password = _get("SMTP_PASS")
    use_tls = _to_bool(_get("SMTP_USE_TLS", "true"), True)
    use_ssl = _to_bool(_get("SMTP_USE_SSL", "false"), False)
    sender = _get("SMTP_SENDER", user)
    if not host or not user or not password:
        LOG.warning("SMTP no configurado; omitiendo envío.")
        return None, None
    timeout = float(_get("SMTP_TIMEOUT", 15))
    ctx = ssl.create_default_context()
    try:
        if use_ssl:
            server = smtplib.SMTP_SSL(host, port, context=ctx, timeout=timeout)
        else:
            server = smtplib.SMTP(host, port, timeout=timeout)
            if use_tls:
                server.starttls(context=ctx)
        server.login(user, password)
        return server, sender
    except (smtplib.SMTPException, OSError, socket.error) as e:
        LOG.exception("SMTP error: %s", e)
        return None, None

def send_email(to_email: str, subject: str, html: str, text: str = None,
               reply_to: Optional[str] = None,
               attachments: Optional[List[Tuple[str, bytes, str]]] = None) -> bool:
    server, sender = _open()
    if not server: return False
    try:
        msg = _build(subject, sender, [to_email], html, text, reply_to, attachments)
        server.send_message(msg); return True
    except smtplib.SMTPException as e:
        LOG.exception("Error enviando a %s: %s", to_email, e); return False
    finally:
        try: server.quit()
        except: pass

def send_email_admins(subject: str, html: str, text: str = None) -> bool:
    admins = _get("ADMIN_EMAILS", "") or ""
    recipients = [e.strip() for e in admins.split(",") if e.strip()]
    if not recipients: return False
    server, sender = _open()
    if not server: return False
    ok = True
    try:
        for to in recipients:
            try:
                msg = _build(subject, sender, [to], html, text)
                server.send_message(msg)
            except Exception:
                ok = False
    finally:
        try: server.quit()
        except: pass
    return ok
