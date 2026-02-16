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
        nombre_cliente = ag.get("client_name", ag.get("client_email", ""))
        fecha = ag.get("created_at")
        if hasattr(fecha, "strftime"):
            fecha_str = fecha.strftime("%Y_%m_%d")
        elif isinstance(fecha, str):
            fecha_str = fecha.split("T")[0].replace("-", "_")
        else:
            fecha_str = "fecha"
        nombre_convenio = f"{nombre_cliente}_{fecha_str}"
        items = list(ag_doc.reference.collection("installments").where("receipt_status","==","PENDING").stream())
        if not items: continue
        with st.expander(f"{nombre_convenio} — {len(items)} pendientes"):
            for inst in items:
                d = inst.to_dict()
                # Visual mejorada para cada cuota pendiente
                color_bg = "#fffbe6"
                color_title = "#ff9800"
                st.markdown(
                    f"""
                    <div style="background:{color_bg};border:1px solid #ffd54f;padding:10px;margin-bottom:8px;border-radius:8px;">
                    <span style="font-size:1.1em;font-weight:bold;color:{color_title};">Cuota {d['number']} (Pendiente de aprobación)</span>
                    <span style="float:right;color:#c62828;font-weight:bold;">Total: ${d['total']:,.2f}</span><br>
                    <span style="font-size:0.95em;">Vencimiento: <b>{d['due_date']}</b></span><br>
                    </div>
                    """, unsafe_allow_html=True
                )
                if d.get("receipt_url"):
                    st.markdown(f"**Comprobante:** [Ver archivo]({d['receipt_url']})")
                else:
                    st.info("Sin comprobante adjunto (declaración manual).")
                st.write(f"Nota del cliente: {d.get('receipt_note','')}")
                note = st.text_input("Observación rechazo", key=f"note_{inst.id}")
                c1,c2 = st.columns(2)
                if c1.button("Aprobar / Marcar pagada", key=f"ok_{inst.id}"):
                    inst.reference.update({
                        "receipt_status": "APPROVED",
                        "paid": True,
                        "paid_at": gcf.SERVER_TIMESTAMP,
                        "receipt_note": d.get("receipt_note", "")
                    })
                    notify_client_receipt_decision(st, db, ag_doc, d["number"], "APROBADO", "")
                    st.success("Pago aprobado. El cliente será notificado y la cuota se marcará como pagada.")
                    if auto_complete_if_all_paid(db, ag_doc):
                        st.success("Convenio COMPLETED.")
                    st.rerun()
                if c2.button("Rechazar", key=f"rej_{inst.id}"):
                    inst.reference.update({
                        "receipt_status": "REJECTED",
                        "receipt_note": note or ""
                    })
                    notify_client_receipt_decision(st, db, ag_doc, d["number"], "RECHAZADO", note or "")
                    st.warning("Pago rechazado. El cliente será notificado.")
                    st.rerun()
                count += 1
    if count == 0:
        st.info("No hay comprobantes pendientes. ¡Todo al día!")
