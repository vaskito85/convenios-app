import requests
import streamlit as st

def upload_to_cloudinary(file, filename):
    cloud_name = st.secrets["CLOUDINARY_CLOUD_NAME"]
    api_key = st.secrets["CLOUDINARY_API_KEY"]
    api_secret = st.secrets["CLOUDINARY_API_SECRET"]
    url = f"https://api.cloudinary.com/v1_1/{cloud_name}/auto/upload"
    files = {"file": (filename, file)}
    data = {}
    auth = (api_key, api_secret)
    response = requests.post(url, files=files, data=data, auth=auth)
    if response.status_code == 200:
        return response.json()["secure_url"]
    else:
        st.error("Error al subir el archivo.")
        return None
