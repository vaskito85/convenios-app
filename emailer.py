import os, ssl, smtplib, socket
import logging
from typing import Iterable, List, Optional, Tuple
from email.utils import formataddr, parseaddr, formatdate, make_msgid
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders

LOG = logging.getLogger(__name__)

def _get_setting(name: str, default=None):
    val = os.environ.get(name)
    if val is not None:
        return val
    try:
        import streamlit as st
        return st.secrets.get(name, default)
    except Exception:
        return default

def _to_bool(v, default=False):
    if v is None:
        return default
    return str(v).strip().lower() in {"1","true","yes","y","on"}

def _normalize_addr(addr: str) -> str:
    name, email = parseaddr(addr or "")
    email = email.strip()
    name = (name or "").strip()
    return formataddr((name, email)) if email else ""

def _split_csv(emails: str) -> List[str]:
    return [e.strip() for e in (emails or "").split(",") if e.strip()]

def _build_message(
    subject: str,
    from_addr: str,
    to_addrs: List[str],
    html_body: str,
    text_body: Optional[str] = None,
    reply_to: Optional[str] = None,
    attachments: Optional[List[Tuple[str, bytes, str]]] = None,
) -> MIMEMultipart:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = _normalize_addr(from_addr)
    msg["To"] = ", ".join(map(_normalize_addr, to_addrs))
    if reply_to:
        msg["Reply-To"] = _normalize_addr(reply_to)
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid()

    if not text_body:
        text_body = "Este correo contiene contenido HTML."

    part1 = MIMEText(text_body, "plain", "utf-8")
    part2 = MIMEText(html_body or "", "html", "utf-8")
    msg.attach(part1)
    msg.attach(part2)

    for att in attachments or []:
        filename, content, mime_type = att
        maintype, subtype = (mime_type.split("/", 1) + ["octet-stream"])[:2]
        part = MIMEBase(maintype, subtype)
        part.set_payload(content)
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", f'attachment; filename="{filename}"')
        msg.attach(part)

    return msg

def _open_smtp():
    host = _get_setting("SMTP_HOST")
    port = int(_get_setting("SMTP_PORT", 587))
    user = _get_setting("SMTP_USER")
    password = _get_setting("SMTP_PASS")
    use_tls = _to_bool(_get_setting("SMTP_USE_TLS", "true"), True)
    use_ssl = _to_bool(_get_setting("SMTP_USE_SSL", "false"), False)
    sender = _get_setting("SMTP_SENDER", user)

    if not host or not user or not password:
        LOG.warning("SMTP no configurado; omitiendo envío.")
        return None, None

    timeout = float(_get_setting("SMTP_TIMEOUT", 15))
    context = ssl.create_default_context()

    try:
        if use_ssl:
            server = smtplib.SMTP_SSL(host, port, context=context, timeout=timeout)
        else:
            server = smtplib.SMTP(host, port, timeout=timeout)
            if use_tls:
                server.starttls(context=context)
        server.login(user, password)
        return server, sender
    except (smtplib.SMTPException, OSError, socket.error) as e:
        LOG.exception("Error abriendo conexión SMTP: %s", e)
        return None, None

def send_email(
    to_email: str,
    subject: str,
    html_body: str,
    text_body: str = None,
    reply_to: Optional[str] = None,
    attachments: Optional[List[Tuple[str, bytes, str]]] = None,
) -> bool:
    server, sender = _open_smtp()
    if not server:
        return False
    try:
        msg = _build_message(subject, sender, [to_email], html_body, text_body, reply_to, attachments)
        server.send_message(msg)
        return True
    except smtplib.SMTPException as e:
        LOG.exception("Error enviando email a %s: %s", to_email, e)
        return False
    finally:
        try:
            server.quit()
        except Exception:
            pass

def send_email_admins(subject: str, html_body: str, text_body: str = None) -> bool:
    admins = _split_csv(_get_setting("ADMIN_EMAILS", ""))
    if not admins:
        LOG.info("No hay ADMIN_EMAILS configurados.")
        return False

    server, sender = _open_smtp()
    if not server:
        return False

    ok_all = True
    try:
        for to in admins:
            try:
                msg = _build_message(subject, sender, [to], html_body, text_body)
                server.send_message(msg)
            except smtplib.SMTPException as e:
                ok_all = False
                LOG.exception("Error enviando email admin a %s: %s", to, e)
    finally:
        try:
            server.quit()
        except Exception:
            pass
    return ok_all

# --- Plantillas rápidas ---
def tpl_user_registered(email: str, full_name: str, role: str, app_url: str):
    return f"""
#### Registro recibido

Hola {full_name or email},
Recibimos tu registro para la plataforma de convenios, con rol solicitado: **{role}**.
Tu cuenta está **pendiente de aprobación** por el administrador. Te avisaremos por correo cuando sea aprobada.
Acceso: {app_url}
"""

def tpl_user_approved(email: str, role: str, app_url: str):
    return f"""
#### Cuenta aprobada

Hola {email}, tu cuenta fue **aprobada** con rol: **{role}**.
Ya podés iniciar sesión y usar la plataforma: {app_url}
"""

def tpl_user_rejected(email: str, note: str, app_url: str):
    return f"""
#### Cuenta rechazada

Hola {email}, tu registro fue **rechazado**.
Motivo: {note or '(sin detalle)'}.
Si creés que es un error, por favor contactanos. Acceso: {app_url}
"""

def tpl_admin_new_user(email: str, role: str, app_url: str):
    return f"""
#### Nuevo usuario registrado

Email: **{email}**
Rol solicitado: **{role}**
Revisá la pestaña de Usuarios (admin) para aprobar o rechazar.
Acceso: {app_url}
"""

def tpl_admin_new_agreement(ag_id: str, operator_email: str, client_email: str, app_url: str):
    return f"""
#### Nuevo convenio creado

Convenio #{ag_id}
Operador: {operator_email}
Cliente: {client_email}
Acceso: {app_url}
"""

def tpl_operator_new_receipt(ag_id: str, inst_num: int, user_email: str, app_url: str):
    return f"""
#### Nuevo comprobante/pago declarado

Convenio #{ag_id} - Cuota {inst_num}
Declarado por: {user_email}
Revisá el pago para aprobar o rechazar. Acceso: {app_url}
"""

def tpl_client_receipt_decision(ag_id: str, inst_num: int, decision: str, note: str, app_url: str):
    return f"""
#### Resultado de verificación de pago

Convenio #{ag_id} - Cuota {inst_num}
Estado: **{decision}**
Detalle: {note or '(sin detalle)'}.
Acceso: {app_url}
"""

def tpl_invite_new_client(email: str, convenio_title: str, app_url: str):
    return f"""
#### Nuevo convenio pendiente de aceptación

Hola {email},
Te han generado un convenio de pago: **{convenio_title}**.
Para aceptarlo, ingresá a la plataforma. Si no tenés cuenta, podés crearla fácilmente.
Acceso: {app_url}
"""
