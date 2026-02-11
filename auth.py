# auth.py
import streamlit as st
import requests
from firebase_admin import auth as admin_auth
from google.cloud import firestore  # tipos
from emailer import (
    send_email, send_email_admins,
    tpl_user_registered, tpl_user_approved, tpl_user_rejected, tpl_admin_new_user
)

APP_URL = None

def _api_key():
    return st.secrets["FIREBASE_WEB_API_KEY"]

def _app_url():
    global APP_URL
    if APP_URL is None:
        APP_URL = st.secrets.get("APP_BASE_URL", "https://example.com")
    return APP_URL

def firebase_sign_in(email: str, password: str):
    url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={_api_key()}"
    payload = {"email": email, "password": password, "returnSecureToken": True}
    r = requests.post(url, json=payload, timeout=15)
    if r.status_code == 200:
        return r.json()
    return None

def get_current_user(db: firestore.Client):
    uid = st.session_state.get("uid")
    if not uid:
        return None
    doc = db.collection("users").document(uid).get()
    return {"uid": uid, **doc.to_dict()} if doc.exists else None

def login_form(db: firestore.Client):
    st.subheader("Iniciar sesión")
    with st.form("login"):
        email = st.text_input("Email").strip().lower()
        password = st.text_input("Contraseña", type="password")
        ok = st.form_submit_button("Entrar")
    if ok:
        data = firebase_sign_in(email, password)
        if not data:
            st.error("Email o contraseña incorrectos.")
            return
        uid = data["localId"]
        # Validar estado en users
        user_doc = db.collection("users").document(uid).get()
        if not user_doc.exists:
            st.error("Tu cuenta no está registrada correctamente. Contactá al administrador.")
            return
        u = user_doc.to_dict()
        status = u.get("status", "PENDING")
        if status != "APPROVED":
            st.warning("Tu cuenta aún no fue aprobada por el administrador.")
            return
        st.session_state["uid"] = uid
        st.rerun()

def signup_form(db: firestore.Client):
    st.subheader("Crear cuenta")
    with st.form("signup"):
        full_name = st.text_input("Nombre y apellido")
        email = st.text_input("Email").strip().lower()
        role = st.selectbox("Rol solicitado", ["cliente", "operador"], index=0)
        password = st.text_input("Contraseña", type="password")
        ok = st.form_submit_button("Registrarme")
    if ok:
        if not email or not password:
            st.error("Email y contraseña son obligatorios.")
            return
        # Crear usuario en Firebase Auth (si ya existe, informamos)
        try:
            u = admin_auth.get_user_by_email(email)
            st.error("Ya existe un usuario con ese email.")
            return
        except Exception:
            pass
        user = admin_auth.create_user(email=email, password=password)
        db.collection("users").document(user.uid).set({
            "email": email,
            "full_name": full_name,
            "role": role,
            "status": "PENDING"
        })
        # Correo al usuario
        send_email(email, "Registro recibido", tpl_user_registered(email, full_name, role, _app_url()))
        # Correo a admins
        send_email_admins("Nuevo usuario registrado", tpl_admin_new_user(email, role, _app_url()))
        st.success("Registro enviado. Tu cuenta quedará activa cuando el administrador la apruebe.")

def ensure_admin_seed(db: firestore.Client):
    """Si no hay usuarios, pide crear el admin y DETIENE la ejecución."""
    try:
        users = list(db.collection("users").limit(1).stream(retry=None, timeout=20))
    except Exception as e:
        st.error("No se pudo consultar Firestore para verificar usuarios (timeout o credenciales).")
        st.exception(e)
        st.stop()

    if users:
        return

    st.warning("No existen usuarios. Creá el usuario administrador inicial.")
    with st.form("seed_admin"):
        email = st.text_input("Email admin").strip().lower()
        name = st.text_input("Nombre completo")
        pwd = st.text_input("Contraseña", type="password")
        ok = st.form_submit_button("Crear admin")

    if ok:
        if not email or not pwd:
            st.error("Email y contraseña son obligatorios.")
            st.stop()
        user = admin_auth.create_user(email=email, password=pwd)
        db.collection("users").document(user.uid).set({
            "email": email, "full_name": name, "role": "admin", "status": "APPROVED"
        })
        st.success("Admin creado. Iniciá sesión con esas credenciales.")
        st.stop()

    st.stop()

def role_badge(role: str) -> str:
    m = {"admin": "⭐ Admin", "operador": "🧰 Operador", "cliente": "👤 Cliente"}
    return m.get(role, role)

def change_password(uid: str, new_password: str):
    admin_auth.update_user(uid, password=new_password)

# ---------- Administración de usuarios ----------
def admin_users_page(db: firestore.Client, user_admin):
    st.subheader("👥 Usuarios")
    st.caption("Aprobá o rechazá registros pendientes. También podés crear usuarios manualmente.")

    with st.expander("➕ Crear usuario (manual)"):
        with st.form("create_user"):
            email = st.text_input("Email").strip().lower()
            full_name = st.text_input("Nombre completo")
            role = st.selectbox("Rol", ["admin","operador","cliente"], index=1)
            temp_pwd = st.text_input("Contraseña temporal", type="password")
            ok = st.form_submit_button("Crear")
        if ok:
            if not email or not temp_pwd:
                st.error("Email y contraseña son obligatorios.")
            else:
                u = admin_auth.create_user(email=email, password=temp_pwd)
                db.collection("users").document(u.uid).set({
                    "email": email, "full_name": full_name, "role": role, "status": "APPROVED"
                })
                st.success("Usuario creado.")

    st.write("### Pendientes de aprobación")
    pending = list(db.collection("users").where("status", "==", "PENDING").stream())
    for d in pending:
        u = d.to_dict()
        cols = st.columns([0.28, 0.22, 0.18, 0.18, 0.14])
        cols[0].write(u.get("full_name") or "-")
        cols[1].write(u.get("email"))
        cols[2].write(role_badge(u.get("role")))
        note = cols[3].text_input("Motivo rechazo (opcional)", key=f"rej_{d.id}")
        c_apr, c_rej = cols[4].columns(2)
        if c_apr.button("Aprobar", key=f"ap_{d.id}"):
            d.reference.update({"status": "APPROVED"})
            send_email(u["email"], "Cuenta aprobada", tpl_user_approved(u["email"], u["role"], _app_url()))
            st.success("Usuario aprobado.")
            st.rerun()
        if c_rej.button("Rechazar", key=f"rj_{d.id}"):
            d.reference.update({"status": "REJECTED", "rejection_note": note})
            send_email(u["email"], "Cuenta rechazada", tpl_user_rejected(u["email"], note, _app_url()))
            st.warning("Usuario rechazado.")
            st.rerun()

    st.write("### Todos los usuarios")
    all_users = list(db.collection("users").stream())
    for d in all_users:
        u = d.to_dict()
        cols = st.columns([0.25, 0.25, 0.2, 0.15, 0.15])
        cols[0].write(u.get("full_name") or "-")
        cols[1].write(u.get("email"))
        cols[2].write(f"{role_badge(u.get('role'))} · {u.get('status','')}")
        if cols[3].button("Reset clave", key=f"reset_{d.id}"):
            temp = "Temp12345!"
            admin_auth.update_user(d.id, password=temp)
            st.info(f"Contraseña temporal: {temp}")
        if d.id != user_admin["uid"] and cols[4].button("Eliminar", key=f"del_{d.id}"):
            try:
                admin_auth.delete_user(d.id)
            except Exception:
                pass
            d.reference.delete()
            st.warning("Usuario eliminado.")
            st.rerun()
