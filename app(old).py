import io
import streamlit as st
import pandas as pd
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

# PDF: reportlab
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.utils import ImageReader

st.set_page_config(page_title="Asistente de Convenios de Pago", page_icon="💳", layout="wide")

MAX_MB = 10
ALLOWED_MIME = {"application/pdf", "image/jpeg", "image/png"}

# ------------------ CONFIGURACIÓN (ADMIN) ------------------

def get_settings(db):
    doc = db.collection("config").document("settings").get()
    if doc.exists:
        data = doc.to_dict() or {}
        return {"interest_enabled": bool(data.get("interest_enabled", False))}
    return {"interest_enabled": False}

def set_settings(db, interest_enabled: bool):
    db.collection("config").document("settings").set(
        {"interest_enabled": bool(interest_enabled)},
        merge=True
    )

def settings_page(db):
    st.subheader("⚙️ Configuración")
    cfg = get_settings(db)
    interest_enabled = st.toggle(
        "Habilitar interés en nuevos convenios", value=cfg["interest_enabled"], key="toggle_interest"
    )
    if st.button("Guardar configuración", key="btn_save_settings"):
        set_settings(db, interest_enabled)
        st.success("Configuración actualizada.")
        st.rerun()

# ------------------ HELPERS UI ------------------

def header(user):
    left, right = st.columns([0.8, 0.2])
    with left:
        st.markdown("### 💳 Asistente de Convenios de Pago")
    with right:
        st.caption(f"Conectado como **{user.get('full_name') or user.get('email')}** ({role_badge(user.get('role'))})")
    if st.button("Cerrar sesión", key="btn_logout"):
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

def _status_badge_txt(status: str) -> str:
    s = (status or "").upper()
    if s == "PENDING_ACCEPTANCE": return ":orange[PENDING_ACCEPTANCE]"
    if s == "REJECTED": return ":red[REJECTED]"
    if s in {"ACTIVE","COMPLETED"}: return ":green["+status+"]"
    if s == "CANCELLED": return ":gray[CANCELLED]"
    return status

def _installment_state_badge(d: dict) -> str:
    if d.get("paid"): return "🟢 PAGADA"
    rs = (d.get("receipt_status") or "").upper()
    if rs == "PENDING": return "🟠 PENDIENTE"
    if rs == "REJECTED": return "🔴 RECHAZADO"
    if rs == "APPROVED": return "🟢 APROBADO"
    return "PENDIENTE"

# ------------------ NOTIFICACIONES ------------------

def notify_agreement_sent(db, ag_ref):
    ag = ag_ref.get().to_dict()
    base = st.secrets.get("APP_BASE_URL","https://example.com")
    subject = f"Convenio enviado para aceptación (#{ag_ref.id})"
    html = f"""
#### Convenio #{ag_ref.id} enviado
Cliente: {ag.get('client_email','')}
Monto: ${ag['principal']:,.2f}
Interés: {ag['interest_rate']*100:.2f}%
Cuotas: {ag['installments']}
Revisalo en: {base}
"""
    op = db.collection("users").document(ag["operator_id"]).get().to_dict()
    for to in {op.get("email"), ag.get("client_email")}:
        if to: send_email(to,subject,html)
    send_email_admins("Nuevo convenio creado",
        tpl_admin_new_agreement(ag_ref.id, op.get("email"), ag.get("client_email"), base)
    )

def notify_agreement_accepted(db, ag_ref):
    ag = ag_ref.get().to_dict()
    base = st.secrets.get("APP_BASE_URL","https://example.com")
    subject = f"Convenio aceptado (#{ag_ref.id})"
    html = f"""
#### Convenio #{ag_ref.id} aceptado
Cliente: {ag.get('client_email','')}
Convenio ACTIVO. Revisalo en: {base}
"""
    op = db.collection("users").document(ag["operator_id"]).get().to_dict()
    for to in {op.get("email"), ag.get("client_email")}:
        if to: send_email(to,subject,html)

def notify_agreement_rejected(db, ag_ref, note):
    ag = ag_ref.get().to_dict()
    base = st.secrets.get("APP_BASE_URL","https://example.com")
    subject = f"Convenio rechazado (#{ag_ref.id})"
    html = f"""
#### Convenio #{ag_ref.id} rechazado
Cliente: {ag.get('client_email','')}
Motivo: {note}
"""
    op = db.collection("users").document(ag["operator_id"]).get().to_dict()
    for to in {op.get("email"), ag.get("client_email")}:
        if to: send_email(to,subject,html)

# ------------------ CREAR CONVENIO ------------------

def create_agreement_page(db, user):
    st.subheader("🆕 Crear convenio")
    cfg = get_settings(db)

    with st.form("create_agreement_form"):
        client_email = st.text_input("Email del cliente").strip().lower()
        client_name = st.text_input("Nombre del cliente (opcional)")
        title = st.text_input("Título del convenio", value="Convenio de pago")
        notes = st.text_area("Notas / Origen de la deuda (opcional)")
        principal = st.number_input("Deuda (principal)", min_value=0.0, value=0.0, step=1000.0)

        # ---- INTERÉS Y MÉTODO (CON CONTROL ADMIN) ----
        if cfg["interest_enabled"]:
            interest_pct = st.number_input(
                "Interés mensual (%)",
                min_value=0.0, value=5.0, step=0.5, format="%.2f",
                key="interest_pct_enabled"
            )
            method_label = st.selectbox(
                "Método de cálculo",
                ["Interés sobre saldo (capital fijo)", "Sistema francés (cuota fija)"],
                key="method_enabled"
            )
        else:
            st.info("⚠ El administrador deshabilitó el interés. Se aplicará 0%.")
            interest_pct = 0.0
            method_label = st.selectbox(
                "Método de cálculo (interés deshabilitado)",
                ["Sistema francés (cuota fija)"],
                disabled=True,
                key="method_disabled"
            )

        installments = st.number_input("Cantidad de cuotas", min_value=1, value=6, step=1)
        start_date = st.date_input("Fecha de primera cuota", value=date.today())

        st.markdown("### Adjuntar documentación (opcional)")
        attach_files = st.file_uploader(
            "PDF/JPG/PNG — puede adjuntar varios",
            type=["pdf","jpg","jpeg","png"],
            accept_multiple_files=True
        )

        ok = st.form_submit_button("Guardar borrador", use_container_width=True)

    if not ok:
        return

    # ---- Validaciones ----
    if not client_email or principal <= 0 or installments < 1:
        st.error("Completá los datos obligatorios.")
        return

    # Validación adjuntos
    if attach_files:
        for f in attach_files:
            size_mb = (f.size or 0) / (1024*1024)
            if size_mb > MAX_MB:
                st.error(f"El archivo '{f.name}' excede {MAX_MB} MB.")
                return
            if f.type not in ALLOWED_MIME:
                st.error(f"Tipo de archivo no permitido: {f.name}")
                return

    # Buscar cliente
    client_doc = None
    q = db.collection("users").where("email","==",client_email).limit(1).stream()
    for d in q:
        if d.to_dict().get("status") == "APPROVED":
            client_doc = d
            break

    method = "declining" if method_label.startswith("Interés") else "french"

    # Crear convenio
    ag_ref = db.collection("agreements").document()
    ag_ref.set({
        "title": title,
        "notes": notes,
        "operator_id": user["uid"],
        "client_id": client_doc.id if client_doc else None,
        "client_email": client_email,
        "principal": round(principal,2),
        "interest_rate": round(interest_pct/100.0,6) if cfg["interest_enabled"] else 0.0,
        "installments": int(installments),
        "method": method,
        "status": "DRAFT",
        "created_at": gcf.SERVER_TIMESTAMP,
        "start_date": start_date.strftime("%Y-%m-%d")
    })

    generate_schedule(db, ag_ref)

    # Subir adjuntos
    if attach_files:
        bucket = get_bucket()
        for f in attach_files:
            safe = f.name.replace("/", "_")
            path = f"agreements/{ag_ref.id}/attachments/{safe}"
            blob = bucket.blob(path)
            blob.upload_from_file(f, content_type=f.type)
            ag_ref.collection("attachments").document().set({
                "name": safe,
                "path": path,
                "content_type": f.type,
                "size": f.size,
                "uploaded_by": user["uid"],
                "uploaded_at": gcf.SERVER_TIMESTAMP
            })

    # Invitación si no existe
    if client_doc is None:
        base = st.secrets.get("APP_BASE_URL","https://example.com")
        send_email(client_email, "Nuevo convenio pendiente de aceptación",
                   tpl_invite_new_client(client_email,title,base))

    st.success("Convenio creado en estado BORRADOR.")
    st.rerun()

def generate_schedule(db, ag_ref):
    ag = ag_ref.get().to_dict()
    for it in ag_ref.collection("installments").stream():
        it.reference.delete()
    if ag["method"] == "declining":
        items = schedule_declining(
            ag["principal"], ag["interest_rate"],
            ag["installments"], date.fromisoformat(ag["start_date"])
        )
    else:
        items = schedule_french(
            ag["principal"], ag["interest_rate"],
            ag["installments"], date.fromisoformat(ag["start_date"])
        )

    batch = db.batch()
    for it in items:
        doc_ref = ag_ref.collection("installments").document()
        batch.set(doc_ref,{
            **it,
            "paid": False,
            "paid_at": None,
            "last_reminder_sent": None,
            "receipt_status": None,
            "receipt_url": None,
            "receipt_note": None
        })
    batch.commit()
    # ------------------ HELPERS PAGO ------------------

def _mark_completed_if_all_paid(db, ag_doc):
    items = list(ag_doc.reference.collection("installments").stream())
    if items and all(it.to_dict().get("paid") for it in items):
        ag_doc.reference.update({"status":"COMPLETED","completed_at":gcf.SERVER_TIMESTAMP})
        ag = ag_doc.to_dict()
        op = db.collection("users").document(ag["operator_id"]).get().to_dict()
        cl_email = ag.get("client_email")
        base = st.secrets.get("APP_BASE_URL","")
        html = f"El convenio #{ag_doc.id} fue marcado como COMPLETADO.<br>Acceso: {base}"
        for to in filter(None,[op.get("email"),cl_email]):
            send_email(to,f"Convenio #{ag_doc.id} COMPLETADO",html)

# ------------------ SUBIDA DE COMPROBANTES (CLIENTE) ------------------

def upload_receipt(db, ag_doc, inst_doc, user):
    st.write("**Subir comprobante (PDF/JPG/PNG). Máx 10MB.**")
    up = st.file_uploader("Archivo", type=["pdf","jpg","jpeg","png"], key=f"upload_{inst_doc.id}")

    if up:
        mb = (up.size or 0) / (1024*1024)
        if mb > MAX_MB:
            st.error("Archivo demasiado grande.")
            return
        if up.type not in ALLOWED_MIME:
            st.error("Tipo de archivo no permitido.")
            return

    if up and st.button("Cargar comprobante", key=f"btn_upload_{inst_doc.id}"):
        bucket = get_bucket()
        name = up.name.replace("/", "_")
        path = f"receipts/{ag_doc.id}/{inst_doc.id}/{name}"
        blob = bucket.blob(path)
        blob.upload_from_file(up, content_type=up.type)
        inst_doc.reference.update({
            "receipt_status":"PENDING",
            "receipt_url": path,
            "receipt_note": None,
            "receipt_uploaded_by": user["uid"],
            "receipt_uploaded_at": gcf.SERVER_TIMESTAMP
        })
        ag = ag_doc.to_dict()
        op = db.collection("users").document(ag["operator_id"]).get().to_dict()
        send_email(op.get("email"),"Nuevo comprobante",
                   tpl_operator_new_receipt(ag_doc.id, inst_doc.to_dict()["number"],
                    user.get("email"), st.secrets.get("APP_BASE_URL","")))
        st.success("Comprobante enviado. Pendiente de aprobación.")

# ------------------ REVISIÓN DEL OPERADOR ------------------

def operator_review_receipts_page(db, user):
    st.subheader("🔎 Pagos/comprobantes pendientes")
    pend = db.collection("agreements").where("operator_id","==",user["uid"]).stream()
    count = 0
    for ag_doc in pend:
        ag = ag_doc.to_dict()
        items = list(ag_doc.reference.collection("installments")
                    .where("receipt_status","==","PENDING").stream())
        if not items:
            continue
        with st.expander(f"Convenio #{ag_doc.id} — {len(items)} pend."):
            for inst in items:
                d = inst.to_dict()
                st.write(f"Cuota {d['number']} — {d['due_date']} — Total ${d['total']:,.2f}")

                if d.get("receipt_url"):
                    try:
                        blob = get_bucket().blob(d["receipt_url"])
                        url = blob.generate_signed_url(expiration=timedelta(minutes=15))
                        st.markdown(url)
                    except Exception as e:
                        st.error(f"Error link: {e}")
                else:
                    st.info("Sin comprobante (declaración manual).")

                note = st.text_input("Observación rechazo", key=f"note_{inst.id}")
                c1,c2 = st.columns(2)

                # APROBAR
                if c1.button("Aprobar / Marcar pagada", key=f"ok_{inst.id}"):
                    inst.reference.update({
                        "receipt_status":"APPROVED",
                        "receipt_note":None,
                        "paid":True,
                        "paid_at":gcf.SERVER_TIMESTAMP
                    })
                    cl_email = ag.get("client_email")
                    if ag.get("client_id"):
                        cl = db.collection("users").document(ag["client_id"]).get().to_dict()
                        cl_email = (cl or {}).get("email") or cl_email

                    send_email(cl_email,"Pago aprobado",tpl_client_receipt_decision(
                        ag_doc.id,d["number"],"APROBADO","",st.secrets.get("APP_BASE_URL","")
                    ))
                    st.success("Pago aprobado.")
                    _mark_completed_if_all_paid(db, ag_doc)
                    st.rerun()

                # RECHAZAR
                if c2.button("Rechazar", key=f"rej_{inst.id}"):
                    inst.reference.update({
                        "receipt_status":"REJECTED",
                        "receipt_note":note or ""
                    })
                    cl_email = ag.get("client_email")
                    if ag.get("client_id"):
                        cl = db.collection("users").document(ag["client_id"]).get().to_dict()
                        cl_email = (cl or {}).get("email") or cl_email

                    send_email(cl_email,"Pago rechazado",tpl_client_receipt_decision(
                        ag_doc.id,d["number"],"RECHAZADO",note or "",st.secrets.get("APP_BASE_URL","")
                    ))
                    st.warning("Pago rechazado.")
                    st.rerun()

                count += 1

    if count == 0:
        st.info("No hay comprobantes pendientes.")
        # ------------------ PDF DEL CONVENIO ------------------

def _build_agreement_pdf(db, ag_doc) -> bytes:
    ag = ag_doc.to_dict()
    items = list(ag_doc.reference.collection("installments")
                 .order_by("number").stream())

    rows = [["N°","Vencimiento","Capital","Interés","Total"]]
    sum_cap=sum_int=sum_tot=0

    for it in items:
        d=it.to_dict()
        sum_cap+=float(d["capital"])
        sum_int+=float(d["interest"])
        sum_tot+=float(d["total"])
        rows.append([
            d["number"], d["due_date"],
            f"${d['capital']:,.2f}",
            f"${d['interest']:,.2f}",
            f"${d['total']:,.2f}"
        ])
    rows.append(["","TOTAL",f"${sum_cap:,.2f}",f"${sum_int:,.2f}",f"${sum_tot:,.2f}"])

    atts = list(ag_doc.reference.collection("attachments").stream())

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
        leftMargin=2*cm, rightMargin=2*cm, topMargin=2*cm, bottomMargin=2*cm)
    story=[]
    styles=getSampleStyleSheet()

    story.append(Paragraph(f"Convenio #{ag_doc.id}",styles["Title"]))
    story.append(Spacer(1,0.3*cm))
    story.append(Paragraph(f"Cliente: {ag.get('client_email')}",styles["Normal"]))
    story.append(Paragraph(f"Operador: {ag.get('operator_id')}",styles["Normal"]))
    story.append(Paragraph(f"Principal: ${ag['principal']:,.2f}",styles["Normal"]))
    story.append(Paragraph(f"Interés mensual: {ag['interest_rate']*100:.2f}%",styles["Normal"]))
    story.append(Paragraph(f"Cuotas: {ag['installments']} - Método: {ag['method']}",styles["Normal"]))
    story.append(Spacer(1,0.3*cm))

    story.append(Paragraph("Calendario de cuotas",styles["Heading2"]))
    tbl=Table(rows)
    tbl.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,0),colors.lightgrey),
        ("GRID",(0,0),(-1,-1),0.25,colors.grey),
        ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),
    ]))
    story.append(tbl)
    story.append(Spacer(1,0.5*cm))

    story.append(Paragraph("Documentación adjunta",styles["Heading2"]))
    if not atts:
        story.append(Paragraph("No hay adjuntos.",styles["Normal"]))
    else:
        bucket=get_bucket()
        for a in atts:
            ad=a.to_dict()
            story.append(Paragraph(f"- {ad['name']} ({ad['content_type']})",styles["Normal"]))
            if ad["content_type"].startswith("image/"):
                try:
                    blob=bucket.blob(ad["path"])
                    img=ImageReader(io.BytesIO(blob.download_as_bytes()))
                    im=Image(img)
                    im._restrictSize(14*cm,10*cm)
                    story.append(im)
                    story.append(Spacer(1,0.2*cm))
                except:
                    pass

    doc.build(story)
    pdf=buf.getvalue()
    buf.close()
    return pdf

# ------------------ PANEL ADMIN ------------------

def admin_dashboard_page(db):
    st.subheader("📊 Panel (admin)")
    states=["DRAFT","PENDING_ACCEPTANCE","ACTIVE","COMPLETED","CANCELLED","REJECTED"]
    counts={s:0 for s in states}
    ags=list(db.collection("agreements").stream())
    for a in ags:
        s=a.to_dict().get("status","DRAFT")
        counts[s]=counts.get(s,0)+1

    st.write("### Estados de convenios")
    for s in states:
        st.markdown(f"- {_status_badge_txt(s)}: **{counts[s]}**")

    total_sent = counts["PENDING_ACCEPTANCE"]+counts["ACTIVE"]+counts["COMPLETED"]
    accepted = counts["ACTIVE"]+counts["COMPLETED"]
    rate = (accepted/total_sent*100) if total_sent else 0
    st.write(f"**Tasa aceptación**: {rate:.1f}%")

# ------------------ PANEL OPERADOR ------------------

def operator_dashboard_page(db,user):
    st.subheader("📈 Mi panel (operador)")
    col=db.collection("agreements").where("operator_id","==",user["uid"])
    ags=list(col.stream())

    if not ags:
        st.info("No tenés convenios todavía.")
        return

    states={"DRAFT":0,"PENDING_ACCEPTANCE":0,"ACTIVE":0,"COMPLETED":0,"CANCELLED":0,"REJECTED":0}
    for a in ags:
        states[a.to_dict().get("status","DRAFT")]+=1

    st.write("### Mis convenios")
    for k,v in states.items():
        st.markdown(f"- {_status_badge_txt(k)}: **{v}**")

# ------------------ LISTADO DE CONVENIOS ------------------

def list_agreements_page(db,user):
    st.subheader("📄 Mis convenios")

    role=user.get("role")
    col=db.collection("agreements")
    if role=="operador":
        q=col.where("operator_id","==",user["uid"])
    elif role=="cliente":
        q=col.where("client_email","==",user["email"])
    else:
        q=col
    ags=list(q.stream())

    for doc in ags:
        ag=doc.to_dict()
        title=ag.get("title","(sin título)")
        stt=_status_badge_txt(ag.get("status"))

        with st.expander(f"[{doc.id}] {title} · {stt}"):

            st.write(
                f"**Deuda:** ${ag['principal']:,.2f} · **Interés:** {ag['interest_rate']*100:.2f}% · "
                f"**Cuotas:** {ag['installments']} · **Método:** {ag['method']}"
            )

            # --------- ACCIONES ---------
            cols=st.columns(6)
            can_edit=(role in ["admin","operador"]) and ag["status"] in ["DRAFT","PENDING_ACCEPTANCE"]

            if can_edit and cols[0].button("Recalcular", key=f"recalc_{doc.id}"):
                generate_schedule(db,doc.reference)
                st.success("Calendario recalculado.")
                st.rerun()

            if can_edit and ag["status"]=="DRAFT" and cols[1].button("Enviar a aceptación", key=f"send_{doc.id}"):
                doc.reference.update({"status":"PENDING_ACCEPTANCE"})
                notify_agreement_sent(db,doc.reference)
                st.success("Enviado.")
                st.rerun()

            if can_edit and cols[2].button("Cancelar", key=f"cancel_{doc.id}"):
                doc.reference.update({"status":"CANCELLED"})
                st.info("Cancelado.")
                st.rerun()

            if role=="cliente" and ag["status"]=="PENDING_ACCEPTANCE":
                if cols[3].button("Aceptar", key=f"accept_{doc.id}"):
                    doc.reference.update({"status":"ACTIVE","accepted_at":gcf.SERVER_TIMESTAMP})
                    notify_agreement_accepted(db,doc.reference)
                    st.success("Aceptado.")
                    st.rerun()
                motivo=st.text_area("Motivo rechazo", key=f"mot_{doc.id}")
                if st.button("Rechazar", key=f"rej_{doc.id}"):
                    doc.reference.update({"status":"REJECTED","rejection_note":motivo})
                    notify_agreement_rejected(db,doc.reference,motivo)
                    st.warning("Rechazado.")
                    st.rerun()

            if role=="admin":
                if cols[4].checkbox("Confirmar eliminación", key=f"chk_{doc.id}"):
                    if cols[5].button("Eliminar", key=f"del_{doc.id}"):
                        try:
                            # borrar cuotas
                            for it in doc.reference.collection("installments").stream():
                                d=it.to_dict()
                                if d.get("receipt_url"):
                                    try: get_bucket().blob(d["receipt_url"]).delete()
                                    except: pass
                                it.reference.delete()
                            # borrar adjuntos
                            for a in doc.reference.collection("attachments").stream():
                                ad=a.to_dict()
                                try: get_bucket().blob(ad["path"]).delete()
                                except: pass
                                a.reference.delete()
                            doc.reference.delete()
                            st.success("Convenio eliminado.")
                            st.rerun()
                        except Exception as e:
                            st.error(str(e))

            # --------- ADJUNTOS ---------
            st.write("### Documentación adjunta")
            atts=list(doc.reference.collection("attachments").stream())
            if not atts:
                st.info("No hay adjuntos.")
            else:
                for a in atts:
                    ad=a.to_dict()
                    r=st.columns([0.7,0.3])
                    r[0].write(f"{ad['name']} · {ad['content_type']}")
                    try:
                        blob=get_bucket().blob(ad["path"])
                        url=blob.generate_signed_url(expiration=timedelta(minutes=15))
                        r[1].markdown(url)
                    except Exception as e:
                        r[1].error("Error link")

            # --------- CALENDARIO ---------
            st.write("### Calendario de cuotas")
            items=list(doc.reference.collection("installments").order_by("number").stream())

            sum_cap=sum(float(it.to_dict()["capital"]) for it in items)
            sum_int=sum(float(it.to_dict()["interest"]) for it in items)
            sum_tot=sum(float(it.to_dict()["total"]) for it in items)

            rows=[]
            for it in items:
                d=it.to_dict()
                rows.append({
                    "N°":d["number"],
                    "Vencimiento":d["due_date"],
                    "Capital":f"${d['capital']:,.2f}",
                    "Interés":f"${d['interest']:,.2f}",
                    "Total":f"${d['total']:,.2f}",
                    "Estado":_installment_state_badge(d)
                })
            rows.append({
                "N°":"",
                "Vencimiento":"TOTAL",
                "Capital":f"${sum_cap:,.2f}",
                "Interés":f"${sum_int:,.2f}",
                "Total":f"${sum_tot:,.2f}",
                "Estado":""
            })
            st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

            # --------- PAGO CLIENTE ---------
            if role=="cliente":
                st.info("Podés subir comprobante o marcar pagada sin comprobante.")
                for it in items:
                    d=it.to_dict()
                    if not d.get("paid") and d.get("receipt_status")!="APPROVED":
                        st.write(f"**Cuota {d['number']}** — Estado: {d.get('receipt_status') or 'SIN COMPROBANTE'}")
                        upload_receipt(db,doc,it,user)
                        if st.button(f"Marcar pagada — {d['number']}", key=f"mp_{it.id}"):
                            it.reference.update({
                                "receipt_status":"PENDING",
                                "receipt_note":"Declaración sin comprobante",
                                "receipt_uploaded_by":user["uid"],
                                "receipt_uploaded_at":gcf.SERVER_TIMESTAMP
                            })
                            op=db.collection("users").document(ag["operator_id"]).get().to_dict()
                            send_email(op.get("email"),"Pago sin comprobante",
                                tpl_operator_new_receipt(doc.id,d["number"],user.get("email"),
                                    st.secrets.get("APP_BASE_URL","")))
                            st.success("Declarado.")
                            st.rerun()

            # --------- ACCIONES OPERADOR ---------
            if role=="operador":
                st.info("Marcar pagada / revertir (con o sin comprobante)")
                for it in items:
                    d=it.to_dict()
                    c1,c2,c3=st.columns([0.25,0.25,0.5])
                    c1.write(f"Cuota {d['number']}")
                    c2.write(d["due_date"])
                    if not d.get("paid"):
                        if c3.button(f"Pagar {d['number']}", key=f"p_{doc.id}_{it.id}"):
                            it.reference.update({
                                "paid":True,
                                "paid_at":gcf.SERVER_TIMESTAMP,
                                "receipt_status": d.get("receipt_status") or "APPROVED",
                                "receipt_note": None
                            })
                            st.success("Marcada como pagada.")
                            _mark_completed_if_all_paid(db,doc)
                            st.rerun()
                    else:
                        if c3.button(f"Revertir {d['number']}", key=f"rv_{doc.id}_{it.id}"):
                            it.reference.update({"paid":False,"paid_at":None})
                            st.info("Revertido.")
                            st.rerun()

            # --------- PDF ---------
            st.write("### Exportar PDF")
            if st.button("Generar PDF", key=f"genpdf_{doc.id}"):
                pdf=_build_agreement_pdf(db,doc)
                st.download_button(
                    "Descargar PDF",
                    data=pdf,
                    file_name=f"convenio_{doc.id}.pdf",
                    mime="application/pdf",
                    key=f"dlpdf_{doc.id}"
                )
                # ------------------ DIAGNÓSTICO ------------------

def diagnostics_page():
    st.subheader("🔎 Diagnóstico")
    try:
        keys=list(st.secrets.keys())
        st.write("Secrets:", ", ".join(keys))
    except:
        st.error("No se pudo leer secrets.")

    try:
        db=get_db()
        test=db.collection("health").document("ping")
        test.set({"ts":gcf.SERVER_TIMESTAMP})
        st.success("Firestore OK.")
    except Exception as e:
        st.error("Error Firestore")
        st.exception(e)

# ------------------ MAIN ------------------

def main():
    init_firebase()
    try:
        db=get_db()
        db.collection("health").document("warmup").set({"ts":gcf.SERVER_TIMESTAMP})
    except Exception as e:
        st.error("No se pudo conectar a Firestore.")
        st.exception(e)
        st.stop()

    ensure_admin_seed(db)

    user=get_current_user(db)
    if not user:
        tab1,tab2=st.tabs(["Iniciar sesión","Registrarme"])
        with tab1: login_form(db)
        with tab2: signup_form(db)
        st.stop()

    header(user)

    menu=[]
    if user["role"]=="admin":
        menu+=["Panel (admin)","Configuración"]
    if user["role"]=="operador":
        menu+=["Panel (operador)","Comprobantes"]
    if user["role"] in ["admin","operador"]:
        menu+=["Crear convenio"]
    menu+=["Mis convenios","Mi contraseña"]
    if user["role"]=="admin":
        menu+=["Usuarios (admin)","Diagnóstico"]

    choice=st.sidebar.radio("Menú",menu, key="menu_radio")

    if choice=="Panel (admin)":
        admin_dashboard_page(db)
    elif choice=="Panel (operador)":
        operator_dashboard_page(db,user)
    elif choice=="Configuración":
        settings_page(db)
    elif choice=="Crear convenio":
        create_agreement_page(db,user)
    elif choice=="Comprobantes":
        operator_review_receipts_page(db,user)
    elif choice=="Mis convenios":
        list_agreements_page(db,user)
    elif choice=="Mi contraseña":
        change_password_page(user)
    elif choice=="Usuarios (admin)":
        admin_users_page(db,user)
    elif choice=="Diagnóstico":
        diagnostics_page()

if __name__=="__main__":
    main()
