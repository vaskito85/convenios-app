import streamlit as st
from datetime import date, timedelta
from firebase_init import init_firebase, get_db, get_bucket
from auth import (
    ensure_admin_seed, login_form, get_current_user, role_badge, change_password,
    signup_form, admin_users_page
)
from emailer import (
    send_email, send_email_admins, tpl_admin_new_agreement, tpl_operator_new_receipt,
    tpl_client_receipt_decision, tpl_invite_new_client, tpl_user_registered, tpl_user_approved, tpl_user_rejected, tpl_admin_new_user
)
from calculations import schedule_declining, schedule_french
from google.cloud import firestore as gcf
import firebase_admin
import traceback

st.set_page_config(page_title="Asistente de Convenios de Pago", page_icon="💳", layout="wide")

# --- UI helpers ---
def header(user):
    left, right = st.columns([0.8, 0.2])
    with left:
        st.markdown("### 💳 Asistente de Convenios de Pago")
    with right:
        st.caption(f"Conectado como **{user.get('full_name') or user.get('email')}** ({role_badge(user.get('role'))})")
    if st.button("Cerrar sesión"):
        st.session_state.clear()
        st.rerun()

def change_password_page(user):
    st.subheader("🔒 Cambiar contraseña")
    with st.form("change_pwd"):
        new = st.text_input("Nueva contraseña", type="password")
        new2 = st.text_input("Repetir nueva contraseña", type="password")
        ok = st.form_submit_button("Actualizar")
        if ok:
            if new != new2 or len(new) < 6:
                st.error("La nueva contraseña debe coincidir y tener al menos 6 caracteres.")
            else:
                change_password(user["uid"], new)
                st.success("Contraseña actualizada.")

# --- Convenios y notificaciones ---
def notify_agreement_sent(db, ag_ref):
    ag = ag_ref.get().to_dict()
    base_url = st.secrets.get("APP_BASE_URL", "https://example.com")
    subject = f"Convenio enviado para aceptación (#{ag_ref.id})"
    html = f"""
#### Convenio #{ag_ref.id} enviado

Cliente: {ag.get('client_email','')}
Monto: ${ag['principal']:,.2f}
Interés: {ag['interest_rate']*100:.2f}%
Cuotas: {ag['installments']}
Ingresá a la app para revisarlo y aceptarlo: {base_url}
"""
    op = db.collection("users").document(ag["operator_id"]).get().to_dict()
    cl = db.collection("users").document(ag["client_id"]).get().to_dict() if ag.get("client_id") else None
    for to in {op.get("email"), ag.get("client_email")}:
        if to:
            send_email(to, subject, html)
    send_email_admins("Nuevo convenio creado", tpl_admin_new_agreement(ag_ref.id, op.get("email"), ag.get("client_email"), base_url))

def notify_agreement_accepted(db, ag_ref):
    ag = ag_ref.get().to_dict()
    base_url = st.secrets.get("APP_BASE_URL", "https://example.com")
    subject = f"Convenio aceptado (#{ag_ref.id})"
    html = f"""
#### Convenio #{ag_ref.id} aceptado

Cliente: {ag.get('client_email','')}
El convenio fue aceptado y está activo. Podrás ver el calendario y registrar pagos.
Acceso: {base_url}
"""
    op = db.collection("users").document(ag["operator_id"]).get().to_dict()
    cl = db.collection("users").document(ag["client_id"]).get().to_dict() if ag.get("client_id") else None
    for to in {op.get("email"), ag.get("client_email")}:
        if to:
            send_email(to, subject, html)

def notify_agreement_rejected(db, ag_ref, note):
    ag = ag_ref.get().to_dict()
    base_url = st.secrets.get("APP_BASE_URL", "https://example.com")
    subject = f"Convenio rechazado (#{ag_ref.id})"
    html = f"""
#### Convenio #{ag_ref.id} rechazado

Cliente: {ag.get('client_email','')}
Motivo: {note}
Ingresá a la app para revisar o crear un nuevo convenio: {base_url}
"""
    op = db.collection("users").document(ag["operator_id"]).get().to_dict()
    for to in {op.get("email"), ag.get("client_email")}:
        if to:
            send_email(to, subject, html)

def create_agreement_page(db, user):
    st.subheader("🆕 Crear convenio")
    with st.form("create_agreement"):
        client_email = st.text_input("Email del cliente").strip().lower()
        client_name = st.text_input("Nombre del cliente (opcional)")
        title = st.text_input("Título del convenio", value="Convenio de pago")
        notes = st.text_area("Notas (opcional)")
        principal = st.number_input("Deuda (principal)", min_value=0.0, value=0.0, step=1000.0, format="%.2f")
        interest_pct = st.number_input("Interés mensual (%)", min_value=0.0, value=5.0, step=0.5, format="%.2f")
        installments = st.number_input("Cantidad de cuotas", min_value=1, value=6, step=1)
        method_label = st.selectbox("Método de cálculo", ["Interés sobre saldo (capital fijo)", "Sistema francés (cuota fija)"])
        start_date = st.date_input("Fecha de primera cuota", value=date.today())
        ok = st.form_submit_button("Calcular y guardar borrador")
        if ok:
            if not client_email or principal <= 0 or installments < 1:
                st.error("Completá los datos obligatorios.")
                return
            # Permitir convenios para emails no registrados
            client_doc = None
            q = db.collection("users").where("email", "==", client_email).limit(1).stream()
            for d in q:
                if d.to_dict().get("status") == "APPROVED":
                    client_doc = d
                    break
            method = "declining" if method_label.startswith("Interés") else "french"
            ag_ref = db.collection("agreements").document()
            ag_ref.set({
                "title": title,
                "notes": notes,
                "operator_id": user["uid"],
                "client_id": client_doc.id if client_doc else None,
                "client_email": client_email,
                "principal": round(principal, 2),
                "interest_rate": round(interest_pct/100.0, 6),
                "installments": int(installments),
                "method": method,
                "status": "PENDING_ACCEPTANCE",
                "created_at": gcf.SERVER_TIMESTAMP,
                "start_date": start_date.strftime("%Y-%m-%d")
            })
            generate_schedule(db, ag_ref)
            # Enviar invitación si el usuario no existe
            if not client_doc:
                base_url = st.secrets.get("APP_BASE_URL", "https://example.com")
                subject = "Nuevo convenio pendiente de aceptación"
                html = tpl_invite_new_client(client_email, title, base_url)
                send_email(client_email, subject, html)
            st.success("Convenio guardado y enviado para aceptación.")
            st.rerun()

def generate_schedule(db, ag_ref):
    ag = ag_ref.get().to_dict()
    for it in ag_ref.collection("installments").stream():
        it.reference.delete()
    if ag["method"] == "declining":
        items = schedule_declining(ag["principal"], ag["interest_rate"], ag["installments"], date.fromisoformat(ag["start_date"]))
    else:
        items = schedule_french(ag["principal"], ag["interest_rate"], ag["installments"], date.fromisoformat(ag["start_date"]))
    batch = db.batch()
    for it in items:
        doc_ref = ag_ref.collection("installments").document()
        batch.set(doc_ref, {**it, "paid": False, "paid_at": None, "last_reminder_sent": None, "receipt_status": None, "receipt_url": None, "receipt_note": None})
    batch.commit()

def list_agreements_page(db, user):
    st.subheader("📄 Mis convenios")
    role = user.get("role")
    col = db.collection("agreements")
    # Cambiado: el cliente ve convenios por email, no solo por UID
    if role == "operador":
        q = col.where("operator_id", "==", user["uid"])
    elif role == "cliente":
        q = col.where("client_email", "==", user["email"])
    else:
        q = col
    agreements = list(q.stream())
    for doc in agreements:
        ag = doc.to_dict()
        title = ag.get('title','(sin título)')
        with st.expander(f"[{doc.id}] {title} · {ag.get('status')} · Cliente: {ag.get('client_email','')}"):
            st.write(
                f"**Deuda:** ${ag['principal']:,.2f} · **Interés:** {ag['interest_rate']*100:.2f}%/mes · "
                f"**Cuotas:** {ag['installments']} · **Método:** {'Capital fijo' if ag['method']=='declining' else 'Francés'}"
            )
            if ag.get("notes"):
                st.caption(ag["notes"])
            cols = st.columns(4)
            can_edit = (role in ["admin","operador"]) and ag["status"] in ["DRAFT","PENDING_ACCEPTANCE"]
            # Botón aceptar/rechazar para cliente
            if role == "cliente" and ag["status"] == "PENDING_ACCEPTANCE":
                c1, c2 = st.columns(2)
                if c1.button("Aceptar convenio", key=f"accept_{doc.id}"):
                    doc.reference.update({"status":"ACTIVE","accepted_at":gcf.SERVER_TIMESTAMP})
                    st.success("Convenio aceptado. ¡Gracias!")
                    notify_agreement_accepted(db, doc.reference)
                    st.rerun()
                with c2:
                    st.write("Rechazar convenio:")
                    motivo = st.text_area("Motivo del rechazo", key=f"motivo_{doc.id}")
                    if st.button("Rechazar convenio", key=f"reject_{doc.id}"):
                        doc.reference.update({"status":"REJECTED","rejection_note":motivo})
                        st.warning("Convenio rechazado.")
                        notify_agreement_rejected(db, doc.reference, motivo)
                        st.rerun()
            # Botones de recalcular, cancelar, etc. para admin/operador
            if can_edit and cols[0].button("Recalcular calendario", key=f"recalc_{doc.id}"):
                generate_schedule(db, doc.reference)
                st.success("Calendario recalculado.")
                st.rerun()
            if can_edit and ag["status"] == "DRAFT" and cols[1].button("Enviar a aceptación", key=f"send_{doc.id}"):
                doc.reference.update({"status": "PENDING_ACCEPTANCE"})
                notify_agreement_sent(db, doc.reference)
                st.success("Enviado a aceptación y notificado por email.")
                st.rerun()
            if role in ["admin","operador"] and ag["status"] in ["DRAFT","PENDING_ACCEPTANCE"] and cols[2].button("Cancelar", key=f"cancel_{doc.id}"):
                doc.reference.update({"status": "CANCELLED"})
                st.info("Convenio cancelado.")
                st.rerun()
            st.write("#### Calendario de cuotas")
            items = list(doc.reference.collection("installments").order_by("number").stream())
            st.dataframe([
                {
                    "Nº": it.to_dict()["number"],
                    "Vencimiento": it.to_dict()["due_date"],
                    "Capital": f"${it.to_dict()['capital']:,.2f}",
                    "Interés": f"${it.to_dict()['interest']:,.2f}",
                    "Total": f"${it.to_dict()['total']:,.2f}",
                    "Estado": "PAGADA" if it.to_dict()["paid"] else (it.to_dict().get("receipt_status") or "PENDIENTE")
                }
                for it in items
            ], hide_index=True, use_container_width=True)

# --- Paneles, métricas, gestión de usuarios, etc. ---
# (Aquí van todas tus funciones originales: admin_dashboard_page, operator_dashboard_page, operator_review_receipts_page, admin_users_page, etc.)
# Si tu archivo original tenía más funciones, simplemente mantenelas aquí sin cambios.

def main():
    init_firebase()
    db = get_db()
    ensure_admin_seed(db)
    user = get_current_user(db)
    if not user:
        login_form(db)
        st.stop()
    header(user)
    items = []
    if user.get("role") == "admin":
        items += ["Panel (admin)", "Usuarios (admin)", "Diagnóstico"]
    if user.get("role") == "operador":
        items += ["Panel (operador)", "Comprobantes", "Crear convenio"]
    if user.get("role") in ["admin","operador"]:
        items += ["Crear convenio"]
    items += ["Mis convenios","Mi contraseña"]
    choice = st.sidebar.radio("Menú", items)
    if choice == "Panel (admin)":
        admin_dashboard_page(db)
    elif choice == "Panel (operador)":
        operator_dashboard_page(db, user)
    elif choice == "Crear convenio":
        create_agreement_page(db, user)
    elif choice == "Comprobantes":
        operator_review_receipts_page(db, user)
    elif choice == "Mis convenios":
        list_agreements_page(db, user)
    elif choice == "Mi contraseña":
        change_password_page(user)
    elif choice == "Usuarios (admin)":
        admin_users_page(db, user)
    elif choice == "Diagnóstico":
        diagnostics_page()

if __name__ == "__main__":
    main()
