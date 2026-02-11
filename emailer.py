# emailer.py
import os, ssl, smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

def _get_setting(name: str, default=None):
    val = os.environ.get(name)
    if val is not None:
        return val
    try:
        import streamlit as st
        return st.secrets.get(name, default)
    except Exception:
        return default

def send_email(to_email: str, subject: str, html_body: str, text_body: str = None):
    host = _get_setting("SMTP_HOST")
    port = int(_get_setting("SMTP_PORT", 587))
    user = _get_setting("SMTP_USER")
    password = _get_setting("SMTP_PASS")
    use_tls = str(_get_setting("SMTP_USE_TLS", "true")).lower() in ["1","true","yes","y"]
    sender = _get_setting("SMTP_SENDER", user)

    if not host or not user or not password:
        print("SMTP no configurado; omitiendo envío.")
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to_email

    if not text_body:
        text_body = "Este correo contiene contenido HTML."
    part1 = MIMEText(text_body, "plain", "utf-8")
    part2 = MIMEText(html_body, "html", "utf-8")
    msg.attach(part1); msg.attach(part2)

    context = ssl.create_default_context()
    if use_tls:
        with smtplib.SMTP(host, port) as server:
            server.starttls(context=context)
            server.login(user, password)
            server.sendmail(sender, [to_email], msg.as_string())
    else:
        with smtplib.SMTP_SSL(host, port, context=context) as server:
            server.login(user, password)
            server.sendmail(sender, [to_email], msg.as_string())
    return True

def send_email_admins(subject: str, html_body: str, text_body: str = None):
    admins = _get_setting("ADMIN_EMAILS", "")
    recipients = [e.strip() for e in admins.split(",") if e.strip()]
    results = []
    for to in recipients:
        results.append(send_email(to, subject, html_body, text_body))
    return all(results) if results else False

# --------- Plantillas rápidas ---------
def tpl_user_registered(email: str, full_name: str, role: str, app_url: str):
    return f"""
    <h3>Registro recibido</h3>
    <p>Hola {full_name or email},</p>
    <p>Recibimos tu registro para la plataforma de convenios, con rol solicitado: <b>{role}</b>.</p>
    <p>Tu cuenta está <b>pendiente de aprobación</b> por el administrador. Te avisaremos por correo cuando sea aprobada.</p>
    <p>Acceso: {app_url}</p>
    """

def tpl_user_approved(email: str, role: str, app_url: str):
    return f"""
    <h3>Cuenta aprobada</h3>
    <p>Hola {email}, tu cuenta fue <b>aprobada</b> con rol: <b>{role}</b>.</p>
    <p>Ya podés iniciar sesión y usar la plataforma: {app_url}</p>
    """

def tpl_user_rejected(email: str, note: str, app_url: str):
    return f"""
    <h3>Cuenta rechazada</h3>
    <p>Hola {email}, tu registro fue <b>rechazado</b>.</p>
    <p>Motivo: {note or '(sin detalle)'}.</p>
    <p>Si creés que es un error, por favor contactanos. Acceso: {app_url}</p>
    """

def tpl_admin_new_user(email: str, role: str, app_url: str):
    return f"""
    <h3>Nuevo usuario registrado</h3>
    <p>Email: <b>{email}</b> | Rol solicitado: <b>{role}</b></p>
    <p>Revisá la pestaña de Usuarios (admin) para aprobar o rechazar.</p>
    <p>Acceso: {app_url}</p>
    """

def tpl_admin_new_agreement(ag_id: str, operator_email: str, client_email: str, app_url: str):
    return f"""
    <h3>Nuevo convenio creado</h3>
    <p>Convenio #{ag_id}</p>
    <p>Operador: {operator_email} | Cliente: {client_email}</p>
    <p>Acceso: {app_url}</p>
    """

def tpl_operator_new_receipt(ag_id: str, inst_num: int, user_email: str, app_url: str):
    return f"""
    <h3>Nuevo comprobante subido</h3>
    <p>Convenio #{ag_id} - Cuota {inst_num}</p>
    <p>Subido por: {user_email}</p>
    <p>Revisá el comprobante para aprobar o rechazar. Acceso: {app_url}</p>
    """

def tpl_client_receipt_decision(ag_id: str, inst_num: int, decision: str, note: str, app_url: str):
    return f"""
    <h3>Resultado de verificación de comprobante</h3>
    <p>Convenio #{ag_id} - Cuota {inst_num}</p>
    <p>Estado: <b>{decision}</b></p>
    <p>Detalle: {note or '(sin detalle)'}.</p>
    <p>Acceso: {app_url}</p>
    """
