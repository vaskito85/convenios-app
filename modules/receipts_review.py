import streamlit as st
from services.storage import signed_url
from services.installments import auto_complete_if_all_paid, mark_paid
from services.notifications import notify_client_receipt_decision
from google.cloud import firestore as gcf
from core.firebase import get_bucket

def render(db, user):
    st.subheader("🔎 Pagos/comprobantes pendientes")
    pend = db.collection("agreements").where("operator_id","==",user["uid"]).stream()
    count = 0
    for ag_doc in pend:
        ag = ag_doc.to_dict()
        items = list(ag_doc.reference.collection("installments").where("receipt_status","==","PENDING").stream())
        if not items: continue
        with st.expander(f"Convenio #{ag_doc.id} — {len(items)} pendientes"):
            for inst in items:
                d = inst.to_dict()
                st.write(f"Cuota {d['number']} — {d['due_date']} — Total ${d['total']:,.2f}")
                # Mostrar comprobante si existe (Cloudinary)
                if d.get("receipt_url"):
                    st.markdown(f"{d['receipt_url']}")
                else:
                    st.info("Sin comprobante adjunto (declaración manual).")
                st.write(f"Nota del cliente: {d.get('receipt_note','')}")
                # Solo mostrar opción de aprobar/rechazar si la cuota está en PENDING
                if d.get("receipt_status") == "PENDING":
                    note = st.text_input("Observación rechazo", key=f"note_{inst.id}")
                    c1,c2 = st.columns(2)
                    if c1.button("Aprobar / Marcar pagada", key=f"ok_{inst.id}"):
                        mark_paid(inst.reference, manual_note="Marcada manualmente por operador")
                        notify_client_receipt_decision(st, db, ag_doc, d["number"], "APROBADO", "")
                        st.success("Pago aprobado.")
                        if auto_complete_if_all_paid(db, ag_doc):
                            st.success("Convenio COMPLETED.")
                        st.rerun()
                    if c2.button("Rechazar", key=f"rej_{inst.id}"):
                        inst.reference.update({"receipt_status":"REJECTED","receipt_note":note or ""})
                        notify_client_receipt_decision(st, db, ag_doc, d["number"], "RECHAZADO", note or "")
                        st.warning("Pago rechazado.")
                        st.rerun()
                count += 1
    if count == 0:
        st.info("No hay comprobantes pendientes.")
