import streamlit as st
from services.agreements import get_user_by_email
from core.firebase import get_db

def render(db, user, ag_doc):
    if not ag_doc or not ag_doc.exists:
        st.info("No hay convenio seleccionado para modificar.")
        return
    ag = ag_doc.to_dict()
    st.subheader("✏️ Modificar convenio")
    client_email = st.text_input("Email del cliente", value=ag.get("client_email","")).strip().lower()
    title = st.text_input("Título del convenio", value=ag.get("title",""))
    notes = st.text_area("Notas / Origen de la deuda (opcional)", value=ag.get("notes",""))
    principal = st.number_input("Deuda (principal)", min_value=0.0, value=ag.get("principal",0.0), step=1000.0, format="%.2f")
    interest_rate = st.number_input("Interés mensual (%)", min_value=0.0, value=ag.get("interest_rate",0.0)*100, step=0.5, format="%.2f")
    installments = st.number_input("Cantidad de cuotas", min_value=1, value=ag.get("installments",6), step=1)
    try:
        import datetime
        if isinstance(ag.get("start_date"), str):
            start_date_value = datetime.datetime.strptime(ag.get("start_date"), "%Y-%m-%d").date()
        else:
            start_date_value = ag.get("start_date") or datetime.date.today()
    except Exception:
        start_date_value = datetime.date.today()
    start_date = st.date_input("Fecha de primera cuota", value=start_date_value)
    ok = st.button("Guardar modificaciones y reenviar")
    if ok:
        if not client_email or not get_user_by_email(db, client_email):
            st.error("Ingresá un email válido para el cliente.")
            return
        ag_doc.reference.update({
            "client_email": client_email,
            "title": title,
            "notes": notes,
            "principal": principal,
            "interest_rate": round(interest_rate/100.0, 6),
            "installments": int(installments),
            "start_date": start_date.strftime("%Y-%m-%d"),
            "status": "PENDING_ACCEPTANCE",
            "rejection_note": "",
        })
        st.success("Convenio modificado y reenviado para aceptación.")
        # Elimina la variable de sesión para volver al menú normal
        if "edit_agreement_id" in st.session_state:
            del st.session_state["edit_agreement_id"]
        st.experimental_rerun()
