import streamlit as st
from datetime import date
from core.firebase import get_bucket
from services.config import get_settings
from services.agreements import get_user_by_email, create_agreement
from services.installments import generate_schedule
from services.storage import upload_file
from services.notifications import notify_agreement_sent
from core.mail import send_email

MAX_MB = 10
ALLOWED_MIME = {"application/pdf","image/jpeg","image/png"}

def render(db, user):
    st.subheader("🆕 Crear convenio")
    cfg = get_settings(db)
    with st.form("create_agreement_form"):
        client_email = st.text_input("Email del cliente").strip().lower()
        title = st.text_input("Título del convenio", value="Convenio de pago")
        notes = st.text_area("Notas / Origen de la deuda (opcional)")
        principal = st.number_input("Deuda (principal)", min_value=0.0, value=0.0, step=1000.0, format="%.2f")
        if cfg["interest_enabled"]:
            interest_pct = st.number_input("Interés mensual (%)", min_value=0.0, value=5.0, step=0.5, format="%.2f", key="interest_pct_enabled")
            method_label = st.selectbox("Método de cálculo",
                ["Interés sobre saldo (capital fijo)", "Sistema francés (cuota fija)"],
                key="method_enabled")
        else:
            st.info("⚠️ El administrador deshabilitó el interés. Se aplicará 0%.")
            interest_pct = 0.0
            method_label = st.selectbox("Método de cálculo (interés deshabilitado)",
                ["Sistema francés (cuota fija)"],
                disabled=True, key="method_disabled")
        installments = st.number_input("Cantidad de cuotas", min_value=1, value=6, step=1)
        start_date = st.date_input("Fecha de primera cuota", value=date.today())
        st.markdown("### Adjuntar documentación (opcional)")
        attach_files = st.file_uploader("PDF/JPG/PNG — puede adjuntar varios", type=["pdf","jpg","jpeg","png"],
            accept_multiple_files=True)
        enviar_aprobacion = st.checkbox("Enviar a aprobación directa", value=False)
        ok = st.form_submit_button("Guardar convenio", use_container_width=True)
    if not ok: return
    if not client_email or principal <= 0 or installments < 1:
        st.error("Completá los datos obligatorios."); return
    if attach_files:
        for f in attach_files:
            size_mb = (f.size or 0) / (1024*1024)
            if size_mb > MAX_MB:
                st.error(f"El archivo '{f.name}' excede {MAX_MB} MB."); return
            if f.type not in ALLOWED_MIME:
                st.error(f"Tipo no permitido: {f.name}"); return
    client_doc = get_user_by_email(db, client_email)
    if client_doc and client_doc.to_dict().get("status") != "APPROVED":
        client_doc = None
    method = "declining" if method_label.startswith("Interés") else "french"
    status = "PENDING_ACCEPTANCE" if enviar_aprobacion else "DRAFT"
    ag_ref = create_agreement(
        db=db, operator_uid=user["uid"], client_email=client_email, client_doc=client_doc,
        title=title, notes=notes, principal=principal,
        interest_rate=round(interest_pct/100.0, 6) if cfg["interest_enabled"] else 0.0,
        installments=int(installments), method=method, start_date_iso=start_date.strftime("%Y-%m-%d"),
        status=status
    )
    generate_schedule(db, ag_ref)
    if attach_files:
        bucket = get_bucket()
        for f in attach_files:
            safe = f.name.replace("/", "_")
            path = f"agreements/{ag_ref.id}/attachments/{safe}"
            upload_file(bucket, path, f, f.type)
            ag_ref.collection("attachments").document().set({
                "name": safe, "path": path, "content_type": f.type, "size": f.size,
                "uploaded_by": user["uid"]
            })
    if status == "PENDING_ACCEPTANCE":
        notify_agreement_sent(st, db, ag_ref)
        st.success("Convenio creado y enviado a aprobación.")
    else:
        st.success("Convenio creado en estado BORRADOR.")
    st.rerun()
