import streamlit as st
from services.agreements import list_agreements_for_role, delete_agreement
from services.installments import mark_paid, mark_unpaid
from core.firebase import get_bucket
from services.pdf_export import build_agreement_pdf
from core.mail import send_email
from services.notifications import notify_agreement_sent

def render(db, user):
    st.subheader("📄 Mis convenios")
    ags = list_agreements_for_role(db, user)
    if not ags:
        st.info("No tenés convenios todavía."); return
    for ag_doc in ags:
        ag = ag_doc.to_dict()
        with st.expander(f"Convenio #{ag_doc.id} — {ag.get('title','')}"):
            st.write(f"Estado: {ag.get('status','DRAFT')}")
            items = list(ag_doc.reference.collection("installments").order_by("number").stream())
            todas_pagas = all(inst.to_dict().get("paid") for inst in items)
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
            # Botón para enviar a aprobación si está en DRAFT
            if user.get("role") == "operador" and ag.get("status") == "DRAFT":
                if st.button("Enviar a aprobación", key=f"aprobacion_{ag_doc.id}"):
                    ag_doc.reference.update({"status": "PENDING_ACCEPTANCE"})
                    notify_agreement_sent(st, db, ag_doc)
                    st.success("Convenio enviado a aprobación.")
                    st.rerun()
            # Botón para finalizar convenio y enviar PDF
            if user.get("role")=="operador" and todas_pagas and ag.get("status") != "COMPLETED":
                if st.button("Finalizar convenio y enviar PDF", key=f"finalizar_{ag_doc.id}"):
                    bucket = get_bucket()
                    # Generar PDF con leyenda "Convenio finalizado"
                    pdf_bytes = build_agreement_pdf(db, bucket, ag_doc, leyenda="Convenio finalizado")
                    # Enviar PDF por email al operador y cliente
                    operador_email = ag.get("operator_email") or user.get("email")
                    cliente_email = ag.get("client_email")
                    asunto = f"Convenio #{ag_doc.id} finalizado"
                    html = f"<h4>Convenio finalizado</h4><p>Adjunto PDF con todas las cuotas pagas.</p>"
                    send_email(operador_email, asunto, html, attachments=[(f"convenio_{ag_doc.id}.pdf", pdf_bytes, "application/pdf")])
                    send_email(cliente_email, asunto, html, attachments=[(f"convenio_{ag_doc.id}.pdf", pdf_bytes, "application/pdf")])
                    st.success("PDF generado y enviado por email al operador y cliente.")
            # Botón para eliminar convenio (solo admin)
            if user.get("role") == "admin":
                if st.button("❌ Eliminar convenio", key=f"del_ag_{ag_doc.id}"):
                    bucket = get_bucket()
                    delete_agreement(db, bucket, ag_doc)
                    st.warning("Convenio eliminado.")
                    st.rerun()
