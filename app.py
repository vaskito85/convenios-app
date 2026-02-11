import streamlit as st
from datetime import date, timedelta
from firebase_init import init_firebase, get_db, get_bucket
from auth import (
    ensure_admin_seed, login_form, get_current_user, role_badge, change_password,
    signup_form, admin_users_page
)
from emailer import (
    send_email, send_email_admins, tpl_admin_new_agreement, tpl_operator_new_receipt,
    tpl_client_receipt_decision, tpl_invite_new_client
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
                "status": "DRAFT",
                "created_at": gcf.SERVER_TIMESTAMP,
                "start_date": start_date.strftime("%Y-%m-%d")
            })
            generate_schedule(db, ag_ref)
            # Enviar invitación si el usuario no existe
            if client_doc is None:
                base_url = st.secrets.get("APP_BASE_URL", "https://example.com")
                subject = "Nuevo convenio pendiente de aceptación"
                html = tpl_invite_new_client(client_email, title, base_url)
                send_email(client_email, subject, html)
            st.success("Convenio guardado en borrador con su calendario de cuotas.")
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
    # --- Comprobantes ---
def upload_receipt(db, ag_doc, inst_doc, user):
    st.write("**Subir comprobante (PDF/JPG/PNG, máx. ~10 MB)**")
    up = st.file_uploader("Archivo", type=["pdf","jpg","jpeg","png"], key=f"up_{inst_doc.id}")
    if up and st.button("Cargar comprobante", key=f"btn_up_{inst_doc.id}"):
        bucket = get_bucket()
        path = f"receipts/{ag_doc.id}/{inst_doc.id}/{up.name}"
        blob = bucket.blob(path)
        blob.upload_from_file(up, content_type=up.type)
        inst_doc.reference.update({
            "receipt_status": "PENDING", "receipt_url": path, "receipt_note": None,
            "receipt_uploaded_by": user["uid"], "receipt_uploaded_at": gcf.SERVER_TIMESTAMP
        })
        ag = ag_doc.to_dict()
        op = db.collection("users").document(ag["operator_id"]).get().to_dict()
        send_email(op["email"], "Nuevo comprobante subido", tpl_operator_new_receipt(
            ag_doc.id, inst_doc.to_dict()["number"], user.get("email"), st.secrets.get("APP_BASE_URL","")
        ))
        st.success("Comprobante cargado. Queda pendiente de revisión.")

def operator_review_receipts_page(db, user):
    st.subheader("🔎 Comprobantes pendientes")
    pending = db.collection("agreements").where("operator_id", "==", user["uid"]).stream()
    count = 0
    for ag_doc in pending:
        ag = ag_doc.to_dict()
        items = ag_doc.reference.collection("installments").where("receipt_status", "==", "PENDING").stream()
        items = list(items)
        if not items:
            continue
        with st.expander(f"Convenio #{ag_doc.id} - {len(items)} comprobante(s) pendiente(s)"):
            for inst in items:
                d = inst.to_dict()
                st.write(f"Cuota {d['number']} - Vence {d['due_date']} - Monto ${d['total']:,.2f}")
                try:
                    blob = get_bucket().blob(d["receipt_url"])
                    url = blob.generate_signed_url(expiration=timedelta(minutes=15))
                    st.markdown(f"{url}")
                except Exception as e:
                    st.error(f"No se pudo generar link de descarga: {e}")
                note = st.text_input("Observación (si rechazás)", key=f"note_{inst.id}")
                c1, c2 = st.columns(2)
                if c1.button("Aprobar", key=f"ap_{inst.id}"):
                    inst.reference.update({"receipt_status": "APPROVED", "receipt_note": None, "paid": True, "paid_at": gcf.SERVER_TIMESTAMP})
                    cl = db.collection("users").document(ag["client_id"]).get().to_dict()
                    send_email(cl["email"], "Comprobante aprobado", tpl_client_receipt_decision(
                        ag_doc.id, d["number"], "APROBADO", "", st.secrets.get("APP_BASE_URL","")
                    ))
                    st.success("Comprobante aprobado y cuota marcada como pagada.")
                    st.rerun()
                if c2.button("Rechazar", key=f"rj_{inst.id}"):
                    inst.reference.update({"receipt_status": "REJECTED", "receipt_note": note or ""})
                    cl = db.collection("users").document(ag["client_id"]).get().to_dict()
                    send_email(cl["email"], "Comprobante rechazado", tpl_client_receipt_decision(
                        ag_doc.id, d["number"], "RECHAZADO", note or "", st.secrets.get("APP_BASE_URL","")
                    ))
                    st.warning("Comprobante rechazado.")
                    st.rerun()
                count += 1
    if count == 0:
        st.info("No hay comprobantes pendientes.")

# --- Paneles ---
def admin_dashboard_page(db):
    st.subheader("📊 Panel (admin) — métricas")
    states = ["DRAFT","PENDING_ACCEPTANCE","ACTIVE","COMPLETED","CANCELLED"]
    counts = {s:0 for s in states}
    agreements = list(db.collection("agreements").stream())
    for a in agreements:
        s = a.to_dict().get("status","DRAFT")
        counts[s] = counts.get(s,0)+1
    c1, c2 = st.columns(2)
    with c1:
        st.write("**Convenios por estado**")
        st.json(counts)
    total_sent = counts.get("PENDING_ACCEPTANCE",0) + counts.get("ACTIVE",0) + counts.get("COMPLETED",0)
    accepted = counts.get("ACTIVE",0) + counts.get("COMPLETED",0)
    rate = (accepted / total_sent * 100) if total_sent else 0
    with c2:
        st.write("**Tasa de aceptación**")
        st.write(f"{rate:.1f}% (sobre {total_sent} enviados)")
    paid, pending = 0,0
    for a in agreements:
        for it in a.reference.collection("installments").stream():
            if it.to_dict().get("paid"):
                paid += 1
            else:
                pending += 1
    st.write("**Estado global de cuotas**")
    st.write(f"Pagadas: {paid} · Pendientes: {pending}")
    dist = {}
    for a in agreements:
        op = a.to_dict().get("operator_id")
        dist[op] = dist.get(op,0)+1
    st.write("**Convenios por operador (IDs)**")
    st.json(dist)
    st.caption("Vista sin datos personales de clientes.")

def operator_dashboard_page(db, user):
    st.subheader("📈 Panel (operador) — mis métricas")
    col = db.collection("agreements").where("operator_id", "==", user["uid"])
    agreements = list(col.stream())
    if not agreements:
        st.info("No tenés convenios asignados aún.")
        return
    states = {"DRAFT":0,"PENDING_ACCEPTANCE":0,"ACTIVE":0,"COMPLETED":0,"CANCELLED":0}
    for a in agreements:
        states[a.to_dict().get("status","DRAFT")] += 1
    c1, c2 = st.columns(2)
    with c1:
        st.write("**Mis convenios por estado**")
        st.json(states)
    total_sent = states["PENDING_ACCEPTANCE"] + states["ACTIVE"] + states["COMPLETED"]
    accepted = states["ACTIVE"] + states["COMPLETED"]
    rate = (accepted/total_sent*100) if total_sent else 0
    with c2:
        st.write("**Mi tasa de aceptación**")
        st.write(f"{rate:.1f}% (sobre {total_sent} enviados)")
    paid, pending = 0,0
    for a in agreements:
        for it in a.reference.collection("installments").stream():
            if it.to_dict().get("paid"):
                paid += 1
            else:
                pending += 1
    st.write("**Cuotas (solo mis convenios)**")
    st.write(f"Pagadas: {paid} · Pendientes: {pending}")
    pend = 0
    for a in agreements:
        pend += len(list(a.reference.collection("installments").where("receipt_status","==","PENDING").stream()))
    st.write(f"**Comprobantes pendientes de revisar**: {pend}")
    # --- Listado con eliminación admin ---
def list_agreements_page(db, user):
    st.subheader("📄 Mis convenios")
    role = user.get("role")
    col = db.collection("agreements")
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
        with st.expander(f"[{doc.id}] {title} · {ag.get('status')}"):
            st.write(
                f"**Deuda:** ${ag['principal']:,.2f} · **Interés:** {ag['interest_rate']*100:.2f}%/mes · "
                f"**Cuotas:** {ag['installments']} · **Método:** {'Capital fijo' if ag['method']=='declining' else 'Francés'}"
            )
            if ag.get("notes"):
                st.caption(ag["notes"])
            cols = st.columns(5 if role=="admin" else 4)
            can_edit = (role in ["admin","operador"]) and ag["status"] in ["DRAFT","PENDING_ACCEPTANCE"]
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
            if role == "cliente" and ag["status"] == "PENDING_ACCEPTANCE" and cols[3].button("Aceptar convenio", key=f"accept_{doc.id}"):
                doc.reference.update({"status":"ACTIVE","accepted_at":gcf.SERVER_TIMESTAMP})
                st.success("Convenio aceptado. ¡Gracias!")
                notify_agreement_accepted(db, doc.reference)
                st.rerun()
            if role == "cliente" and ag["status"] == "PENDING_ACCEPTANCE":
                motivo = st.text_area("Motivo del rechazo", key=f"motivo_{doc.id}")
                if st.button("Rechazar convenio", key=f"reject_{doc.id}"):
                    doc.reference.update({"status":"REJECTED","rejection_note":motivo})
                    st.warning("Convenio rechazado.")
                    notify_agreement_rejected(db, doc.reference, motivo)
                    st.rerun()
            if role == "admin":
                with cols[4]:
                    confirm = st.checkbox(f"Confirmar eliminar {doc.id}", key=f"chk_del_{doc.id}")
                    if st.button("Eliminar convenio", key=f"del_{doc.id}"):
                        if not confirm:
                            st.warning("Tildá la confirmación para eliminar.")
                        else:
                            try:
                                for it in doc.reference.collection("installments").stream():
                                    d = it.to_dict()
                                    if d.get("receipt_url"):
                                        try:
                                            get_bucket().blob(d["receipt_url"]).delete()
                                        except Exception:
                                            pass
                                    it.reference.delete()
                                doc.reference.delete()
                                st.success("Convenio eliminado.")
                                st.rerun()
                            except Exception as e:
                                st.error(f"No se pudo eliminar: {e}")
            st.write("#### Calendario de cuotas")
            items = list(doc.reference.collection("installments").order_by("number").stream())
            st.dataframe([
                {
                    "N°": it.to_dict()["number"],
                    "Vencimiento": it.to_dict()["due_date"],
                    "Capital": f"${it.to_dict()['capital']:,.2f}",
                    "Interés": f"${it.to_dict()['interest']:,.2f}",
                    "Total": f"${it.to_dict()['total']:,.2f}",
                    "Estado": "PAGADA" if it.to_dict()["paid"] else (it.to_dict().get("receipt_status") or "PENDIENTE")
                }
                for it in items
            ], hide_index=True, use_container_width=True)
            if role == "cliente":
                for it in items:
                    d = it.to_dict()
                    if not d.get("paid") and d.get("receipt_status") != "APPROVED":
                        st.write(f"**Cuota {d['number']}** — Estado: {d.get('receipt_status') or 'SIN COMPROBANTE'}")
                        upload_receipt(db, doc, it, user)
            if role == "operador":
                st.info("Para revisar comprobantes pendientes, usá el menú: Comprobantes")

# --- Diagnóstico (solo admin) ---
def diagnostics_page():
    st.subheader("🔎 Diagnóstico")
    try:
        secret_keys = list(st.secrets.keys())
        st.write("**Claves en secrets:**", ", ".join(secret_keys))
        st.write("FIREBASE_PROJECT_ID:", st.secrets.get("FIREBASE_PROJECT_ID"))
        st.write("APP_BASE_URL:", st.secrets.get("APP_BASE_URL"))
    except Exception as e:
        st.error(f"No se pudo leer st.secrets: {e}")
    try:
        st.write("**Firebase inicializado:**", bool(firebase_admin._apps))
    except Exception as e:
        st.error(f"Error inspeccionando Firebase Admin: {e}")
    try:
        db = get_db()
        test_ref = db.collection("health").document("ping")
        test_ref.set({"ts": gcf.SERVER_TIMESTAMP})
        doc = test_ref.get().to_dict()
        st.success(f"Firestore OK. Documento de prueba: {doc}")
    except Exception as e:
        st.error(f"Error de Firestore: {e}")
        st.code("".join(traceback.format_exception(e)), language="text")

# --- Main ---
def main():
    init_firebase()
    try:
        db = get_db()
        db.collection("health").document("warmup").set({"ts": gcf.SERVER_TIMESTAMP})
    except Exception as e:
        st.error("No se pudo conectar a Firestore (warmup). Revisá Secrets y la clave del Service Account.")
        st.exception(e)
        st.stop()
    ensure_admin_seed(db)
    user = get_current_user(db)
    if not user:
        tab_login, tab_signup = st.tabs(["Iniciar sesión", "Registrarme"])
        with tab_login:
            login_form(db)
        with tab_signup:
            signup_form(db)
        st.stop()
    header(user)
    # Menú contextual
    menu = []
    if user.get("role") == "admin":
        menu += ["Panel (admin)"]
    if user.get("role") == "operador":
        menu += ["Panel (operador)", "Comprobantes"]
    if user.get("role") in ["admin","operador"]:
        menu += ["Crear convenio"]
    menu += ["Mis convenios", "Mi contraseña"]
    if user.get("role") == "admin":
        menu += ["Usuarios (admin)", "Diagnóstico"]
    choice = st.sidebar.radio("Menú", menu)
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
        if user.get("role") == "admin":
            diagnostics_page()
        else:
            st.warning("Sección disponible solo para administradores.")

if __name__ == "__main__":
    main()
