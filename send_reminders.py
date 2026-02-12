import os
from datetime import datetime, date, timedelta
from typing import List, Dict, Tuple, Optional

try:
    import streamlit as st
except Exception:
    st = None

import pytz
from firebase_init import init_firebase, get_db
from emailer import send_email
from google.cloud import firestore as gcf

def _get(name: str, default=None):
    if st is not None:
        try:
            val = st.secrets.get(name, None)
            if val is not None:
                return val
        except Exception:
            pass
    return os.environ.get(name, default)

APP_BASE_URL = _get("APP_BASE_URL", "https://example.com")
APP_TZ       = _get("APP_TZ", "America/Argentina/Buenos_Aires")
REMINDER_DAYS_BEFORE = int(_get("REMINDER_DAYS_BEFORE", 3))
REMINDER_DAYS_AFTER  = int(_get("REMINDER_DAYS_AFTER", 3))
REMINDER_COOLDOWN_DAYS = int(_get("REMINDER_COOLDOWN_DAYS", 3))
TZ = pytz.timezone(APP_TZ)

def _today_local() -> date:
    return datetime.now(TZ).date()

def _should_remind(due: date, last_sent: Optional[datetime], today: date) -> bool:
    days = (due - today).days
    if days < 0:
        if abs(days) > REMINDER_DAYS_AFTER:
            return False
    else:
        if days > REMINDER_DAYS_BEFORE:
            return False
    if last_sent is None:
        return True
    delta = datetime.now(TZ) - last_sent.astimezone(TZ)
    return delta.days >= REMINDER_COOLDOWN_DAYS

def _who_to_notify(db, ag: Dict) -> Tuple[Optional[str], Optional[str]]:
    client_email = ag.get("client_email")
    op_email = None
    op_id = ag.get("operator_id")
    if op_id:
        op_doc = db.collection("users").document(op_id).get()
        if op_doc.exists:
            op_email = (op_doc.to_dict() or {}).get("email")
    cl_id = ag.get("client_id")
    if cl_id:
        cl_doc = db.collection("users").document(cl_id).get()
        if cl_doc.exists:
            client_email = (cl_doc.to_dict() or {}).get("email") or client_email
    return client_email, op_email

def _build_subject_and_html(ag_id: str, inst_num: int, due: date, days_to_due: int, total: float) -> Tuple[str, str]:
    if days_to_due > 0:
        subject = f"Recordatorio: cuota #{inst_num} vence el {due.isoformat()} (Convenio #{ag_id})"
        msg = f"""
        <h3>Recordatorio de vencimiento</h3>
        <p>Convenio <b>#{ag_id}</b> – Cuota <b>{inst_num}</b></p>
        <p>Vence el <b>{due.isoformat()}</b> (en {days_to_due} día{'s' if days_to_due != 1 else ''}).</p>
        <p>Importe: <b>${total:,.2f}</b></p>
        <p>Acceso a la plataforma: {APP_BASE_URL}</p>
        """
    elif days_to_due == 0:
        subject = f"Vence hoy la cuota #{inst_num} (Convenio #{ag_id})"
        msg = f"""
        <h3>Vencimiento hoy</h3>
        <p>Convenio <b>#{ag_id}</b> – Cuota <b>{inst_num}</b></p>
        <p><b>Hoy</b> vence esta cuota.</p>
        <p>Importe: <b>${total:,.2f}</b></p>
        <p>Acceso a la plataforma: {APP_BASE_URL}</p>
        """
    else:
        subject = f"Aviso: cuota #{inst_num} vencida (Convenio #{ag_id})"
        msg = f"""
        <h3>Cuota vencida</h3>
        <p>Convenio <b>#{ag_id}</b> – Cuota <b>{inst_num}</b></p>
        <p>Venció el <b>{due.isoformat()}</b> (hace {abs(days_to_due)} día{'s' if abs(days_to_due) != 1 else ''}).</p>
        <p>Importe: <b>${total:,.2f}</b></p>
        <p>Acceso a la plataforma: {APP_BASE_URL}</p>
        """
    return subject, msg

def run_reminders() -> Dict[str, int]:
    init_firebase()
    db = get_db()
    today = _today_local()

    sent = 0
    checked = 0
    errors = 0

    for ag_doc in db.collection("agreements").where("status", "==", "ACTIVE").stream():
        ag = ag_doc.to_dict() or {}
        client_email, op_email = _who_to_notify(db, ag)
        if not client_email:
            continue

        inst_col = ag_doc.reference.collection("installments").where("paid", "==", False)
        for it in inst_col.stream():
            d = it.to_dict() or {}
            try:
                due = date.fromisoformat(d["due_date"])
            except Exception:
                continue

            days_to_due = (due - today).days
            last_sent = d.get("last_reminder_sent")

            if not _should_remind(due, last_sent, today):
                continue

            subject, html = _build_subject_and_html(
                ag_id=ag_doc.id,
                inst_num=d.get("number", 0),
                due=due,
                days_to_due=days_to_due,
                total=float(d.get("total", 0.0))
            )

            ok = send_email(client_email, subject, html)
            if op_email:
                send_email(op_email, f"[Copia] {subject}", html)

            it.reference.update({"last_reminder_sent": gcf.SERVER_TIMESTAMP})

            sent += 1
            checked += 1

    return {"checked": checked, "sent": sent, "errors": errors}

def _render_streamlit():
    from auth import ensure_admin_seed, get_current_user, login_form, role_badge
    st.set_page_config(page_title="Recordatorios de cuotas", page_icon="⏰", layout="wide")

    init_firebase()
    db = get_db()
    ensure_admin_seed(db)

    user = get_current_user(db)
    if not user:
        login_form(db); st.stop()
    if user.get("role") != "admin":
        st.error("Solo administradores pueden ejecutar recordatorios."); st.stop()

    left, right = st.columns([0.8, 0.2])
    with left: st.markdown("### ⏰ Envío de recordatorios de cuotas")
    with right: st.caption(f"Conectado como **{user.get('full_name') or user.get('email')}** ({role_badge(user.get('role'))})")

    if st.button("Enviar recordatorios ahora"):
        res = run_reminders()
        st.success(f"Listo. Procesadas: {res['checked']} · Enviadas: {res['sent']} · Errores: {res['errors']}")

def main():
    if st is not None and st._is_running_with_streamlit:
        _render_streamlit()
    else:
        res = run_reminders()
        print(f"[send_reminders] Procesadas: {res['checked']} · Enviadas: {res['sent']} · Errores: {res['errors']}")

if __name__ == "__main__":
    main()
