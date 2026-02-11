# firebase_init.py
import json
import streamlit as st
import firebase_admin
from firebase_admin import credentials, firestore as admin_firestore

def init_firebase():
    """
    Inicializa Firebase de manera segura evitando doble inicialización.
    """
    if firebase_admin._apps:
        return

    # Leer JSON del secret (string) y convertir a dict
    cred_dict = json.loads(st.secrets["FIREBASE_CREDENTIALS"])
    cred = credentials.Certificate(cred_dict)

    # Inicializar la app de Firebase con la credencial del Service Account
    firebase_admin.initialize_app(cred)

def get_db():
    """
    Devuelve un cliente Firestore usando el Admin SDK ya inicializado.
    """
    return admin_firestore.client()
