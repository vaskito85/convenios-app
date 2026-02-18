import streamlit as st
from core.firebase import init_firebase, get_db
from core.auth import ensure_admin_seed, get_current_user, login_form, signup_form, admin_users_page
from modules.common import header, change_password_page
from modules import settings as page_settings
from modules import dashboard_admin, dashboard_operator, agreements_create, agreements_list, receipts_review, agreement_edit

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

# --- Cabecera visual ---
st.markdown("""
    <style>
    .stButton>button {font-size:1em;padding:8px 18px;border-radius:8px;}
    .stTextInput>div>input {border-radius:8px;}
    .stFileUploader>div {border-radius:8px;}
    .menu-icon {margin-right:8px;}
    .sidebar-content {font-size:1.05em;}
    </style>
    <div style="background:#1976d2;padding:18px 0 10px 0;border-radius:0 0 12px 12px;margin-bottom:10px;">
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

    pendientes = get_pendientes_comprobantes(db, user) if user.get("role")=="operador" else 0
    pendientes_cliente = get_pendientes_convenios_cliente(db, user) if user.get("role")=="cliente" else 0
    menu = []
    if user.get("role")=="admin":
        menu += ["🗂️ Panel (admin)", "⚙️ Configuración"]
    if user.get("role")=="operador":
        menu += ["📊 Panel (operador)", f"📥 Comprobantes ({pendientes})"]
    if user.get("role") in ["admin","operador"]:
        menu += ["📝 Crear convenio"]
    menu += ["📄 Mis convenios"]
    if user.get("role")=="cliente" and pendientes_cliente > 0:
        menu += [f"⏳ Convenios por aceptar ({pendientes_cliente})"]
    # Solo operador y admin ven "Modificar convenio"
    if user.get("role") in ["admin","operador"]:
        menu += ["✏️ Modificar convenio"]
    menu += ["🔒 Mi contraseña"]
    if user.get("role")=="admin":
        menu += ["👥 Usuarios (admin)"]

    with st.sidebar:
        st.markdown('<div class="sidebar-content">', unsafe_allow_html=True)
        choice = st.radio("Menú", menu, key="menu_radio")
        st.markdown('</div>', unsafe_allow_html=True)

    # --- Mapping del menú ---
    if choice.endswith("Panel (admin)"):
        dashboard_admin.render(db)
    elif choice.endswith("Panel (operador)"):
        dashboard_operator.render(db, user)
    elif choice.endswith("Configuración"):
        page_settings.render(db)
    elif choice.endswith("Crear convenio"):
        agreements_create.render(db, user)
    elif choice.startswith("📥 Comprobantes"):
        receipts_review.render(db, user)
    elif choice.startswith("📄 Mis convenios") or choice.startswith("⏳ Convenios por aceptar"):
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
