import streamlit as st
from datetime import date, datetime
from firebase_init import init_firebase, get_db
from auth import ensure_admin_seed, login_form, get_current_user, role_badge, change_password
from emailer import send_email
from calculations import schedule_declining, schedule_french
from google.cloud import firestore

st.set_page_config(page_title="Asistente de Convenios de Pago", page_icon="💳", layout="wide")

def header(user):
    left, right = st.columns([0.8, 0.2])
    with left: st.markdown("### 💳 Asistente de Convenios de Pago")
    with right:
        st.caption(f"Conectado como **{user.get('full_name') or user.get('email')}** ({role_badge(user.get('role'))})")
        if st.button("Cerrar sesión"):
            st.session_state.clear(); st.rerun()

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

def notify_agreement_sent(db, ag_ref):
    ag = ag_ref.get().to_dict()
    base_url = st.secrets.get("APP_BASE_URL", "https://example.com")
    subject = f"Convenio enviado para aceptación (#{ag_ref.id})"
    html = f"""
    <h3>Convenio #{ag_ref.id} enviado</h3>
    <p>Cliente: {ag.get('client_email','')}</p>
    <p>Monto: ${ag['principal']:,.2f} | Interés: {ag['interest_rate']*100:.2f}% | Cuotas: {ag['installments']}</p>
    <p>Ingresá a la app para revisarlo y aceptarlo: {base_url}</p>
    """
    op = db.collection("users").document(ag["operator_id"]).get().to_dict()
    cl = db.collection("users").document(ag["client_id"]).get().to_dict()
    for to in {op.get("email"), cl.get("email")}:
        if to: send_email(to, subject, html)

def notify_agreement_accepted(db, ag_ref):
    ag = ag_ref.get().to_dict()
    base_url = st.secrets.get("APP_BASE_URL", "https://example.com")
    subject = f"Convenio aceptado (#{ag_ref.id})"
    html = f"""
    <h3>Convenio #{ag_ref.id} aceptado</h3>
    <p>Cliente: {ag.get('client_email','')}</p>
    <p>El convenio fue aceptado y está activo. Podrás ver el calendario y registrar pagos.</p>
    <p>Acceso: {base_url}</p>
    """
    op = db.collection("users").document(ag["operator_id"]).get().to_dict()
    cl = db.collection("users").document(ag["client_id"]).get().to_dict()
    for to in {op.get("email"), cl.get("email")}:
        if to: send_email(to, subject, html)

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
            st.error("Completá los datos obligatorios."); return

        client_doc = None
        q = db.collection("users").where("email", "==", client_email).limit(1).stream()
        for d in q: client_doc = d; break

        if client_doc is None:
            st.info("El cliente no existe en usuarios. Crealo desde 'Usuarios (admin)' o compartí el link para que se registre.")
            return

        method = "declining" if method_label.startswith("Interés") else "french"
        ag_ref = db.collection("agreements").document()
        ag_ref.set({
            "title": title, "notes": notes,
            "operator_id": user["uid"], "client_id": client_doc.id, "client_email": client_email,
            "principal": round(principal, 2), "interest_rate": round(interest_pct/100.0, 6),
            "installments": int(installments), "method": method, "status": "DRAFT",
            "created_at": firestore.SERVER_TIMESTAMP, "start_date": start_date.strftime("%Y-%m-%d")
        })
        generate_schedule(db, ag_ref)
        st.success("Convenio guardado en borrador con su calendario de cuotas.")
        st.rerun()

def generate_schedule(db, ag_ref):
    ag = ag_ref.get().to_dict()
    for it in ag_ref.collection("installments").stream(): it.reference.delete()
    if ag["method"] == "declining":
        items = schedule_declining(ag["principal"], ag["interest_rate"], ag["installments"], date.fromisoformat(ag["start_date"]))
    else:
        items = schedule_french(ag["principal"], ag["interest_rate"], ag["installments"], date.fromisoformat(ag["start_date"]))
    batch = db.batch()
    for it in items:
        doc_ref = ag_ref.collection("installments").document()
        batch.set(doc_ref, {**it, "paid": False, "paid_at": None, "last_reminder_sent": None})
    batch.commit()

def admin_users_page(db, user):
    st.subheader("👥 Gestión de usuarios")
    with st.expander("➕ Crear usuario"):
        with st.form("create_user"):
            email = st.text_input("Email").strip().lower()
            full_name = st.text_input("Nombre completo")
            role = st.selectbox("Rol", ["admin","operador","cliente"], index=1)
            temp_pwd = st.text_input("Contraseña temporal", type="password")
            ok = st.form_submit_button("Crear")
        if ok:
            if not email or not temp_pwd:
                st.error("Email y contraseña son obligatorios.")
            else:
                from firebase_admin import auth as admin_auth
                u = admin_auth.create_user(email=email, password=temp_pwd)
                db.collection("users").document(u.uid).set({"email": email, "full_name": full_name, "role": role})
                st.success("Usuario creado.")

    st.write("### Usuarios existentes")
    for d in db.collection("users").stream():
        u = d.to_dict()
        cols = st.columns([0.3, 0.3, 0.25, 0.15])
        cols[0].write(u.get("full_name") or "-")
        cols[1].write(u.get("email"))
        cols[2].write(role_badge(u.get("role")))
        if d.id != user["uid"] and cols[3].button("Eliminar", key=f"del_{d.id}"):
            from firebase_admin import auth as admin_auth
            try: admin_auth.delete_user(d.id)
            except Exception: pass
            d.reference.delete(); st.warning("Usuario eliminado."); st.rerun()

def list_agreements_page(db, user):
    st.subheader("📄 Mis convenios")
    role = user.get("role")
    col = db.collection("agreements")
    if role == "operador": q = col.where("operator_id", "==", user["uid"])
    elif role == "cliente": q = col.where("client_id", "==", user["uid"])
    else: q = col
    agreements = list(q.stream())

    for doc in agreements:
        ag = doc.to_dict()
        with st.expander(f"[{doc.id}] {ag.get('title','(sin título)')} · {ag.get('status')} · Cliente: {ag.get('client_email','')}"):
            st.write(
                f"**Deuda:** ${ag['principal']:,.2f} · **Interés:** {ag['interest_rate']*100:.2f}%/mes · "
                f"**Cuotas:** {ag['installments']} · **Método:** {('Capital fijo' if ag['method']=='declining' else 'Francés')}"
            )
            if ag.get("notes"): st.caption(ag["notes"])

            cols = st.columns(4)
            can_edit = (role in ["admin","operador"]) and ag["status"] in ["DRAFT","PENDING_ACCEPTANCE"]
            if can_edit and cols[0].button("Recalcular calendario", key=f"recalc_{doc.id}"):
                generate_schedule(db, doc.reference); st.success("Calendario recalculado."); st.rerun()
            if can_edit and ag["status"] == "DRAFT" and cols[1].button("Enviar a aceptación", key=f"send_{doc.id}"):
                doc.reference.update({"status": "PENDING_ACCEPTANCE"}); notify_agreement_sent(db, doc.reference)
                st.success("Enviado a aceptación y notificado por email."); st.rerun()
            if role in ["admin","operador"] and ag["status"] in ["DRAFT","PENDING_ACCEPTANCE"] and cols[2].button("Cancelar", key=f"cancel_{doc.id}"):
                doc.reference.update({"status": "CANCELLED"}); st.info("Convenio cancelado."); st.rerun()
            if role == "cliente" and ag["status"] == "PENDING_ACCEPTANCE" and cols[3].button("Aceptar convenio", key=f"accept_{doc.id}"):
                doc.reference.update({"status":"ACTIVE","accepted_at":firestore.SERVER_TIMESTAMP})
                st.success("Convenio aceptado. ¡Gracias!"); notify_agreement_accepted(db, doc.reference); st.rerun()

            st.write("#### Calendario de cuotas")
            items = list(doc.reference.collection("installments").order_by("number").stream())
            st.dataframe([{
                "N°": it.to_dict()["number"],
                "Vencimiento": it.to_dict()["due_date"],
                "Capital": f"${it.to_dict()['capital']:,.2f}",
                "Interés": f"${it.to_dict()['interest']:,.2f}",
                "Total": f"${it.to_dict()['total']:,.2f}",
                "Estado": "PAGADA" if it.to_dict()["paid"] else "PENDIENTE"
            } for it in items], hide_index=True, use_container_width=True)

            if role in ["admin","operador"]:
                st.write("##### Registrar pagos")
                for it in items:
                    data = it.to_dict()
                    c1, c2, c3, c4 = st.columns([0.2, 0.3, 0.3, 0.2])
                    c1.write(f"Cuota {data['number']}"); c2.write(data["due_date"])
                    if not data["paid"] and c3.button("Marcar como pagada", key=f"paid_{doc.id}_{it.id}"):
                        it.reference.update({"paid": True, "paid_at": firestore.SERVER_TIMESTAMP})
                        st.success(f"Cuota {data['number']} marcada como pagada."); st.rerun()
                    if data["paid"] and c4.button("Desmarcar", key=f"unpaid_{doc.id}_{it.id}"):
                        it.reference.update({"paid": False, "paid_at": None})
                        st.info(f"Cuota {data['number']} revertida a pendiente."); st.rerun()

def user_label(db, uid: str) -> str:
    d = db.collection("users").document(uid).get()
    if not d.exists: return "(desconocido)"
    u = d.to_dict(); return u.get("full_name") or u.get("email")

def main():
    init_firebase()
    db = get_db()
    ensure_admin_seed(db)
    user = get_current_user(db)
    if not user:
        login_form(db); st.stop()
    header(user)
    items = []
    if user.get("role") in ["admin","operador"]: items.append("Crear convenio")
    items += ["Mis convenios","Mi contraseña"]
    if user.get("role") == "admin": items.append("Usuarios (admin)")
    choice = st.sidebar.radio("Menú", items)
    if choice == "Crear convenio": create_agreement_page(db, user)
    elif choice == "Mis convenios": list_agreements_page(db, user)
    elif choice == "Mi contraseña": change_password_page(user)
    elif choice == "Usuarios (admin)": admin_users_page(db, user)

if __name__ == "__main__":
    main()