import streamlit as st
from core.auth import role_badge, change_password

def header(user):
    left, right = st.columns([0.8, 0.2])
    with left:
        st.markdown("### 💳 Asistente de Convenios de Pago")
    with right:
        st.caption(f"Conectado como **{user.get('full_name') or user.get('email')}** ({role_badge(user.get('role'))})")
    if st.button("Cerrar sesión", key="btn_logout"):
        st.session_state.clear(); st.rerun()

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
