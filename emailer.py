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