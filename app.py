import streamlit as st
from core.firebase import init_firebase, get_db
from core.auth import ensure_admin_seed, get_current_user, login_form, signup_form, admin_users_page
from modules.common import header, change_password_page
from modules import settings as page_settings
from modules import dashboard_admin, dashboard_operator, agreements_create, agreements_list, receipts_review

def get_pendientes_comprobantes(db, user):
    count = 0
    for ag_doc in db.collection("agreements").where("operator_id","==",user["uid"]).stream():
        items = list(ag_doc.reference.collection("installments").where("receipt_status","==","PENDING").stream())
        count += len(items)
    return count

def get_pendientes_convenios_cliente(db, user):
    count = 0
    for ag_doc in db.collection("agreements").where("client_email","==",user["email"]).stream():
        ag = ag_doc.to_dict()
        if ag.get("status") == "PENDING_ACCEPTANCE":
            count += 1
    return count

st.set_page_config(page_title="Asistente de Convenios de Pago", page_icon="💳", layout="wide")

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
    menu=[]
    pendientes = get_pendientes_comprobantes(db, user) if user.get("role")=="operador" else 0
    pendientes_cliente = get_pendientes_convenios_cliente(db, user) if user.get("role")=="cliente" else 0
    if user.get("role")=="admin":
        menu += ["Panel (admin)","Configuración"]
    if user.get("role")=="operador":
        menu += ["Panel (operador)", f"Comprobantes ({pendientes})"]
    if user.get("role") in ["admin","operador"]:
        menu += ["Crear convenio"]
    menu += ["Mis convenios"]
    if user.get("role")=="cliente" and pendientes_cliente > 0:
        menu += [f"Convenios por aceptar ({pendientes_cliente})"]
    menu += ["Mi contraseña"]
    if user.get("role")=="admin":
        menu += ["Usuarios (admin)"]
    choice = st.sidebar.radio("Menú", menu, key="menu_radio")
    if choice=="Panel (admin)":
        dashboard_admin.render(db)
    elif choice=="Panel (operador)":
        dashboard_operator.render(db, user)
    elif choice=="Configuración":
        page_settings.render(db)
    elif choice=="Crear convenio":
        agreements_create.render(db, user)
    elif choice.startswith("Comprobantes"):
        receipts_review.render(db, user)
    elif choice=="Mis convenios" or choice.startswith("Convenios por aceptar"):
        agreements_list.render(db, user)
    elif choice=="Mi contraseña":
        change_password_page(user)
    elif choice=="Usuarios (admin)":
        admin_users_page(db, user)

if __name__=="__main__":
    main()
