import json, streamlit as st, firebase_admin
from firebase_admin import credentials
from google.cloud import firestore

def init_firebase():
    if "firebase_initialized" in st.session_state:
        return
    cred_dict = json.loads(st.secrets["FIREBASE_CREDENTIALS"])
    cred = credentials.Certificate(cred_dict)
    firebase_admin.initialize_app(cred, {"projectId": st.secrets["FIREBASE_PROJECT_ID"]})
    st.session_state["firebase_initialized"] = True

def get_db() -> firestore.Client:
    return firestore.Client(project=st.secrets["FIREBASE_PROJECT_ID"])