import json
import streamlit as st
import firebase_admin
from firebase_admin import credentials
from google.cloud import firestore

def init_firebase():
    """
    Inicializa Firebase de manera segura evitando doble inicialización.
    """
    # Si Firebase ya está inicializado, no lo volvemos a hacer
    if firebase_admin._apps:
        return

    # Leer JSON del secret (string)
    raw_json = st.secrets["FIREBASE_CREDENTIALS"]

    # Convertir JSON string -> dict
    cred_dict = json.loads(raw_json)

    # Crear credenciales del Admin SDK
    cred = credentials.Certificate(cred_dict)

    # Inicializar app de Firebase
    firebase_admin.initialize_app(cred)

def get_db() -> firestore.Client:
    """
    Retorna un cliente Firestore válido usando el project_id.
    """
    project_id = st.secrets["FIREBASE_PROJECT_ID"]
    return firestore.Client(project=project_id)
