import os
from datetime import datetime, date
import pytz

try:
    import streamlit as st
except Exception:
    st = None

from core.firebase import init_firebase, get_db
from core.mail import send_email

def _get(name, default=None):
    if st is not None:
        try:
            val = st.secrets.get(name, None)
            if val is not None: return val
        except Exception:
            pass
    return os.environ.get(name, default)

APP_BASE_URL = _get("APP_BASE_URL","https://example.com")
APP_TZ = _get("APP_TZ","America/Argentina/Buenos_Aires")
REMINDER_DAYS_BEFORE = int(_get("REMINDER_DAYS_BEFORE",3))
REMINDER_DAYS_AFTER  = int(_get("REMINDER_DAYS_AFTER",3))
REMINDER_COOLDOWN_DAYS = int(_get("REMINDER_COOLDOWN_DAYS",3))
TZ = pytz.timezone(APP_TZ)

def _today() -> date: return datetime.now(TZ).date()

def _should_remind(due: date, last_sent, today: date) -> bool:
    days = (due - today).days
    if days < 0 and abs(days) > REMINDER_DAYS_AFTER: return False
    if days > 0 and days > REMINDER_DAYS_BEFORE: return False
    if last_sent is None: return True
    delta = datetime.now(TZ) - last_sent
    try:
        # last_sent puede ser Firestore Timestamp
        delta_days = (delta.days if hasattr(delta,"days") else 9999)
    except Exception:
        delta_days = 9999
    return delta_days >= REMINDER_COOLDOWN_DAYS

def run_reminders():
    init_firebase()
    db = get_db()
    today = _today()

    checked = sent = 0
    for ag_doc in db.collection("agreements").where("status","==","ACTIVE").stream():
        ag = ag_doc.to_dict() or {}
        client_email = ag.get("client_email")
        if ag.get("client_id"):
            cl = db.collection("users").document(ag["client_id"]).get()
            if cl.exists:
                client_email = (cl.to_dict() or {}).get("email") or client_email

        if not client_email: continue

        for it in ag_doc.reference.collection("installments").where("paid","==",False).stream():
            d = it.to_dict() or {}
            try:
                due = date.fromisoformat(d["due_date"])
            except Exception:
                continue
            last_sent = d.get("last_reminder_sent")
            if not _should_remind(due, last_sent, today):
                continue
            days_to_due = (due - today).days
            if days_to_due > 0:
                subject = f"Recordatorio: cuota #{d.get('number')} vence el {due.isoformat()} (Convenio #{ag_doc.id})"
                html = f"<h3>Recordatorio de vencimiento</h3><p>Vence el <b>{due.isoformat()}</b> (en {days_to_due} días).</p><p>Acceso: {APP_BASE_URL}</p>"
            elif days_to_due == 0:
                subject = f"Vence hoy la cuota #{d.get('number')} (Convenio #{ag_doc.id})"
                html = f"<h3>Vencimiento hoy</h3><p>Hoy vence esta cuota.</p><p>Acceso: {APP_BASE_URL}</p>"
            else:
                subject = f"Aviso: cuota #{d.get('number')} vencida (Convenio #{ag_doc.id})"
                html = f"<h3>Cuota vencida</h3><p>Venció el <b>{due.isoformat()}</b>.</p><p>Acceso: {APP_BASE_URL}</p>"

            send_email(client_email, subject, html)
            it.reference.update({"last_reminder_sent": datetime.now()})
            sent += 1; checked += 1
    return {"checked": checked, "sent": sent}

if __name__=="__main__":
    res = run_reminders()
    print(f"[send_reminders] Procesadas: {res['checked']} · Enviadas: {res['sent']}")
