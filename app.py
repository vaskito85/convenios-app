import streamlit as st
from core.firebase import init_firebase, get_db
from core.auth import ensure_admin_seed, get_current_user, login_form, signup_form, admin_users_page
from modules.common import header, change_password_page
from modules import settings as page_settings
from modules import dashboard_admin, dashboard_operator, agreements_create, agreements_list, receipts_review

st.set_page_config(page_title="Asistente de Convenios de Pago", page_icon="💳", layout="wide")

def main():
    init_firebase()
    db = get_db()
    # Warmup
    db.collection("health").document("warmup").set({"ok": True})
    ensure_admin_seed(db)
    user = get_current_user(db)
    if not user:
        tab_login, tab_signup = st.tabs(["Iniciar sesión", "Registrarme"])
        with tab_login: login_form(db)
        with tab_signup: signup_form(db)
        st.stop()
    header(user)
    menu=[]
    if user.get("role")=="admin":
        menu += ["Panel (admin)","Configuración"]
    if user.get("role")=="operador":
        menu += ["Panel (operador)","Comprobantes"]
    if user.get("role") in ["admin","operador"]:
        menu += ["Crear convenio"]
    menu += ["Mis convenios","Mi contraseña"]
    if user.get("role")=="admin":
        menu += ["Usuarios (admin)"]
    # Oculta el menú lateral de páginas internas
    choice = st.radio("Menú", menu, key="menu_radio")
    if choice=="Panel (admin)":
        dashboard_admin.render(db)
    elif choice=="Panel (operador)":
        dashboard_operator.render(db, user)
    elif choice=="Configuración":
        page_settings.render(db)
    elif choice=="Crear convenio":
        agreements_create.render(db, user)
    elif choice=="Comprobantes":
        receipts_review.render(db, user)
    elif choice=="Mis convenios":
        agreements_list.render(db, user)  # Cambiado: muestra la página correcta
    elif choice=="Mi contraseña":
        change_password_page(user)
    elif choice=="Usuarios (admin)":
        admin_users_page(db, user)

if __name__=="__main__":
    main()

