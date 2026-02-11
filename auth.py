import streamlit as st
import requests
from firebase_admin import auth as admin_auth
from google.cloud import firestore

def _api_key():
    return st.secrets["FIREBASE_WEB_API_KEY"]

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
        res = firebase_sign_in(email, password)
        if not res:
            st.error("Email o contraseña incorrectos.")
            return
        uid = res["localId"]
        st.session_state["uid"] = uid
        ud = db.collection("users").document(uid).get()
        if not ud.exists:
            db.collection("users").document(uid).set({"email": email, "full_name": "", "role": "cliente"})
        st.rerun()

def ensure_admin_seed(db: firestore.Client):
    users = list(db.collection("users").limit(1).stream())
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
            st.error("Email y contraseña son obligatorios."); st.stop()
        user = admin_auth.create_user(email=email, password=pwd)
        db.collection("users").document(user.uid).set({
            "email": email, "full_name": name, "role": "admin"
        })
        st.success("Admin creado. Iniciá sesión con esas credenciales.")
        st.rerun()

def change_password(uid: str, new_password: str):
    admin_auth.update_user(uid, password=new_password)

def role_badge(role: str) -> str:
    m = {"admin": "⭐ admin", "operador": "🧰 operador", "cliente": "👤 cliente"}
    return m.get(role, role)