import json
import os
from typing import Optional
import firebase_admin
from firebase_admin import credentials, firestore as admin_firestore, storage as admin_storage

try:
    import streamlit as st
except Exception:
    st = None  # permitir uso fuera de Streamlit

_DB = None
_BUCKET = None

def _get_secret(name: str, default=None):
    if st is not None:
        try:
            val = st.secrets.get(name, None)
            if val is not None:
                return val
        except Exception:
            pass
    return os.environ.get(name, default)

def init_firebase() -> None:
    """
    Inicializa Firebase Admin una sola vez.
    Prioriza credenciales embebidas en secrets (FIREBASE_CREDENTIALS).
    Si no están, intenta Application Default Credentials (ADC).
    Configura bucket si está disponible.
    """
    if firebase_admin._apps:
        return

    cred = None
    cred_json = _get_secret("FIREBASE_CREDENTIALS")
    project_id = _get_secret("FIREBASE_PROJECT_ID")

    if cred_json:
        if isinstance(cred_json, str):
            cred_dict = json.loads(cred_json)
        else:
            cred_dict = cred_json
        cred = credentials.Certificate(cred_dict)
        if not project_id:
            project_id = cred_dict.get("project_id")
    else:
        cred = credentials.ApplicationDefault()

    bucket_name = _get_secret("FIREBASE_STORAGE_BUCKET")
    if not bucket_name and project_id:
        bucket_name = f"{project_id}.appspot.com"

    opts = {}
    if bucket_name:
        opts["storageBucket"] = bucket_name

    firebase_admin.initialize_app(cred, opts)

def get_db():
    """Devuelve cliente Firestore (Admin SDK)."""
    global _DB
    if _DB is None:
        _DB = admin_firestore.client()
    return _DB

def get_bucket():
    """Devuelve el bucket de Firebase Storage configurado."""
    global _BUCKET
    if _BUCKET is None:
        _BUCKET = admin_storage.bucket()
    return _BUCKET
