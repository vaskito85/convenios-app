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
#### Nuevo comprobante subido

Convenio #{ag_id} - Cuota {inst_num}
Subido por: {user_email}
Revisá el comprobante para aprobar o rechazar. Acceso: {app_url}
"""

def tpl_client_receipt_decision(ag_id: str, inst_num: int, decision: str, note: str, app_url: str):
    return f"""
#### Resultado de verificación de comprobante

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
