import streamlit as st
from services.agreements import list_agreements_for_role, delete_agreement
from services.installments import mark_paid, mark_unpaid
from core.firebase import get_bucket
from services.pdf_export import build_agreement_pdf
from core.mail import send_email
from services.notifications import (
    notify_agreement_sent,
    notify_agreement_accepted,
    notify_agreement_rejected
)
from services.cloudinary_upload import upload_to_cloudinary

def render(db, user):
    st.subheader("📄 Mis convenios")
    ags = list_agreements_for_role(db, user)
    if not ags:
        st.info("No tenés convenios todavía."); return
    for ag_doc in ags:
        ag = ag_doc.to_dict()
        items = list(ag_doc.reference.collection("installments").order_by("number").stream())
        todas_pagas = all(inst.to_dict().get("paid") for inst in items)
        # --- MENÚ DE ACCIÓN ARRIBA ---
        with st.expander(f"Convenio #{ag_doc.id} — {ag.get('title','')}"):
            # OPERADOR: enviar a aprobación si está en DRAFT
            if user.get("role") == "operador" and ag.get("status") == "DRAFT":
                if st.button("Enviar a aprobación", key=f"aprobacion_{ag_doc.id}"):
                    ag_doc.reference.update({"status": "PENDING_ACCEPTANCE"})
                    notify_agreement_sent(st, db, ag_doc)
                    st.success("Convenio enviado a aprobación.")
                    st.rerun()
            # OPERADOR: finalizar convenio y enviar PDF
            if user.get("role")=="operador" and todas_pagas and ag.get("status") != "COMPLETED":
                if st.button("Finalizar convenio y enviar PDF", key=f"finalizar_{ag_doc.id}"):
                    bucket = get_bucket()
                    pdf_bytes = build_agreement_pdf(db, bucket, ag_doc, leyenda="Convenio finalizado")
                    operador_email = ag.get("operator_email") or user.get("email")
                    cliente_email = ag.get("client_email")
                    asunto = f"Convenio #{ag_doc.id} finalizado"
                    html = f"<h4>Convenio finalizado</h4><p>Adjunto PDF con todas las cuotas pagas.</p>"
                    send_email(operador_email, asunto, html, attachments=[(f"convenio_{ag_doc.id}.pdf", pdf_bytes, "application/pdf")])
                    send_email(cliente_email, asunto, html, attachments=[(f"convenio_{ag_doc.id}.pdf", pdf_bytes, "application/pdf")])
                    st.success("PDF generado y enviado por email al operador y cliente.")
            # CLIENTE: aceptar o rechazar convenio si está en PENDING_ACCEPTANCE
            if user.get("role") == "cliente" and ag.get("status") == "PENDING_ACCEPTANCE":
                col1, col2 = st.columns(2)
                if col1.button("Aceptar convenio", key=f"aceptar_{ag_doc.id}"):
                    ag_doc.reference.update({"status": "ACTIVE", "accepted_at": st.session_state.get("now")})
                    notify_agreement_accepted(st, db, ag_doc)
                    st.success("Convenio aceptado.")
                    st.rerun()
                motivo_rechazo = col2.text_input("Motivo rechazo (opcional)", key=f"motivo_{ag_doc.id}")
                if col2.button("Rechazar convenio", key=f"rechazar_{ag_doc.id}"):
                    ag_doc.reference.update({"status": "REJECTED", "rejection_note": motivo_rechazo})
                    notify_agreement_rejected(st, db, ag_doc, motivo_rechazo)
                    st.warning("Convenio rechazado.")
                    st.rerun()
            # ADMIN: eliminar convenio
            if user.get("role") == "admin":
                if st.button("❌ Eliminar convenio", key=f"del_ag_{ag_doc.id}"):
                    bucket = get_bucket()
                    delete_agreement(db, bucket, ag_doc)
                    st.warning("Convenio eliminado.")
                    st.rerun()
            # --- CONTENIDO DEL CONVENIO ---
            st.write(f"Estado: {ag.get('status','DRAFT')}")
            for inst in items:
                d = inst.to_dict()
                st.write(f"Cuota {d['number']} — {d['due_date']} — Total ${d['total']:,.2f}")
                st.write(f"Pagada: {'Sí' if d.get('paid') else 'No'}")
                # Permite al operador marcar como pagada sin intervención del cliente
                if user.get("role")=="operador" and not d.get("paid"):
                    if st.button(f"Marcar pagada cuota {d['number']} (manual)", key=f"paid_{inst.id}"):
                        mark_paid(inst.reference, manual_note="Marcada manualmente por operador")
                        st.success("Cuota marcada como pagada.")
                        st.rerun()
                if d.get("paid"):
                    if st.button(f"Revertir cuota {d['number']}", key=f"unpaid_{inst.id}"):
                        mark_unpaid(inst.reference)
                        st.warning("Cuota revertida a impaga.")
                        st.rerun()
                # CLIENTE: declarar pago y subir comprobante
                if user.get("role") == "cliente" and not d.get("paid"):
                    st.markdown("**¿Pagaste esta cuota?**")
                    comprobante = st.file_uploader(
                        f"Subí tu comprobante para cuota {d['number']} (PDF/JPG/PNG)", 
                        type=["pdf", "jpg", "jpeg", "png"], 
                        key=f"comprobante_{inst.id}"
                    )
                    nota_cliente = st.text_input("Nota para el operador (opcional)", key=f"nota_{inst.id}")
                    if st.button(f"Declarar pago cuota {d['number']}", key=f"declarar_pago_{inst.id}"):
                        url_comprobante = None
                        if comprobante is not None:
                            url_comprobante = upload_to_cloudinary(comprobante, comprobante.name)
                        inst.reference.update({
                            "receipt_status": "PENDING",
                            "receipt_url": url_comprobante,
                            "receipt_note": nota_cliente,
                            "paid": False
                        })
                        st.success("¡Pago declarado! El operador revisará tu comprobante.")
                        st.rerun()
                # Mostrar comprobante al operador
                if user.get("role") == "operador" and d.get("receipt_url"):
                    st.markdown(f"[Ver comprobante]({d['receipt_url']})")
