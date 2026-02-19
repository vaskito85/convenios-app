import streamlit as st
from core.firebase import init_firebase, get_db
from core.auth import ensure_admin_seed, get_current_user, login_form, signup_form, admin_users_page
from modules.common import header, change_password_page
from modules import settings as page_settings
from modules import dashboard_admin, dashboard_operator, agreements_create, agreements_list, receipts_review, agreement_edit

# --- Cargar CSS separado ---
with open("style.css") as f:
    st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)

st.set_page_config(page_title="Asistente de Convenios de Pago", page_icon="💳", layout="wide")

st.markdown("""
<div class="menu-lateral">
    <h2 style="color:white;text-align:center;margin:0;">💳 Asistente de Convenios de Pago</h2>
</div>
""", unsafe_allow_html=True)

def main():
    init_firebase()
    db = get_db()
    db.collection("health").document("warmup").set({"ok": True})
    ensure_admin_seed(db)
    user = get_current_user(db)
    if not user:
        tab_login, tab_signup = st.tabs(["Iniciar sesión", "Registrarme"])
        with tab_login: login_form(db)
        with tab_signup: signup_form(db)
        st.stop()
    header(user)

    # Menú visual
    menu = []
    if user.get("role")=="admin":
        menu += ["🗂️ Panel (admin)", "⚙️ Configuración"]
    if user.get("role")=="operador":
        menu += ["📊 Panel (operador)", "📥 Comprobantes"]
    if user.get("role") in ["admin","operador"]:
        menu += ["📝 Crear convenio"]
    menu += ["📄 Mis convenios"]
    if user.get("role")=="cliente":
        menu += ["⏳ Convenios por aceptar"]
    if user.get("role") in ["admin","operador"]:
        menu += ["✏️ Modificar convenio"]
    menu += ["🔒 Mi contraseña"]
    if user.get("role")=="admin":
        menu += ["👥 Usuarios (admin)"]

    with st.sidebar:
        st.markdown('<div class="menu-lateral">', unsafe_allow_html=True)
        choice = st.radio("Menú", menu, key="menu_radio")
        st.markdown('</div>', unsafe_allow_html=True)

    if choice.endswith("Panel (admin)"):
        dashboard_admin.render(db)
    elif choice.endswith("Panel (operador)"):
        dashboard_operator.render(db, user)
    elif choice.endswith("Configuración"):
        page_settings.render(db)
    elif choice.endswith("Crear convenio"):
        agreements_create.render(db, user)
    elif "Comprobantes" in choice:
        receipts_review.render(db, user)
    elif "Mis convenios" in choice or "Convenios por aceptar" in choice:
        agreements_list.render(db, user)
    elif choice.endswith("Mi contraseña"):
        change_password_page(user)
    elif choice.endswith("Usuarios (admin)"):
        admin_users_page(db, user)
    elif choice.endswith("Modificar convenio"):
        ag_id = st.session_state.get("edit_agreement_id")
        ag_doc = db.collection("agreements").document(ag_id).get() if ag_id else None
        agreement_edit.render(db, user, ag_doc)

if __name__=="__main__":
    main()
