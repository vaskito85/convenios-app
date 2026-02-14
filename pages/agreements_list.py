import streamlit as st
from datetime import date
from core.firebase import get_bucket
from services.config import get_settings
from services.agreements import get_user_by_email, create_agreement, list_agreements_for_role
from services.installments import mark_paid, mark_unpaid
from services.storage import upload_file
from services.notifications import notify_agreement_sent

def render(db, user):
    st.subheader("📄 Mis convenios")
    ags = list_agreements_for_role(db, user)
    if not ags:
        st.info("No tenés convenios todavía."); return
    for ag_doc in ags:
        ag = ag_doc.to_dict()
        st.expander(f"Convenio #{ag_doc.id} — {ag.get('title','')}")
        st.write(f"Estado: {ag.get('status','DRAFT')}")
        items = list(ag_doc.reference.collection("installments").order_by("number").stream())
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
