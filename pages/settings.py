import streamlit as st
from services.config import get_settings, set_settings

def render(db):
    st.subheader("⚙️ Configuración")
    cfg = get_settings(db)
    interest_enabled = st.toggle("Habilitar interés en nuevos convenios", value=cfg["interest_enabled"], key="toggle_interest")
    if st.button("Guardar configuración", key="btn_save_settings"):
        set_settings(db, interest_enabled)
        st.success("Configuración actualizada."); st.rerun()
