# firebase_init.py
import json
import streamlit as st
import firebase_admin
from firebase_admin import credentials, firestore as admin_firestore, storage as admin_storage

def init_firebase():
    """
    Inicializa Firebase de manera segura evitando doble inicialización.
    Configura opcionalmente el bucket de Storage.
    """
    if firebase_admin._apps:
        return

    cred_dict = json.loads(st.secrets["FIREBASE_CREDENTIALS"])
    cred = credentials.Certificate(cred_dict)

    # Si tienes un bucket explícito en secrets, úsalo. Si no, usa <project_id>.appspot.com
    bucket_name = st.secrets.get("FIREBASE_STORAGE_BUCKET", f'{st.secrets["FIREBASE_PROJECT_ID"]}.appspot.com')
    firebase_admin.initialize_app(cred, {"storageBucket": bucket_name})

def get_db():
    """Devuelve cliente Firestore usando Admin SDK."""
    return admin_firestore.client()

def get_bucket():
    """Devuelve el bucket de Firebase Storage configurado en la app Admin SDK."""
    return admin_storage.bucket()
