import json
import streamlit as st
import firebase_admin
from firebase_admin import credentials
from google.cloud import firestore

def init_firebase():
    # Si ya existe la app de Firebase, NO volver a inicializarla
    if firebase_admin._apps:
        return

    cred_dict = json.loads(st.secrets["FIREBASE_CREDENTIALS"])
    cred = credentials.Certificate(cred_dict)
    firebase_admin.initialize_app(cred, {
        "projectId": st.secrets["FIREBASE_PROJECT_ID"]
    })

def get_db() -> firestore.Client:
    return firestore.Client(project=st.secrets["FIREBASE_PROJECT_ID"])
