from typing import Optional, List, Dict
from google.cloud import firestore as gcf

def get_user_by_email(db, email: str):
    q = db.collection("users").where("email","==",email).limit(1).stream()
    for d in q:
        return d
    return None

def create_agreement(db, operator_uid: str, client_email: str, client_doc,
    title: str, notes: str, principal: float,
    interest_rate: float, installments: int, method: str,
    start_date_iso: str, status: str = "DRAFT"):
    ag_ref = db.collection("agreements").document()
    ag_ref.set({
        "title": title,
        "notes": notes,
        "operator_id": operator_uid,
        "client_id": client_doc.id if client_doc else None,
        "client_email": client_email,
        "principal": round(principal,2),
        "interest_rate": interest_rate,
        "installments": int(installments),
        "method": method,
        "status": status,
        "created_at": gcf.SERVER_TIMESTAMP,
        "start_date": start_date_iso
    })
    return ag_ref

def list_agreements_for_role(db, user: Dict):
    role = user.get("role")
    col = db.collection("agreements")
    if role == "operador":
        q = col.where("operator_id","==", user["uid"])
    elif role == "cliente":
        q = col.where("client_email","==", user["email"])
    else:
        q = col
    return list(q.stream())

def delete_agreement(db, bucket, ag_doc):
    # borrar cuotas + recibos
    for it in ag_doc.reference.collection("installments").stream():
        d = it.to_dict()
        if d.get("receipt_url"):
            try: bucket.blob(d["receipt_url"]).delete()
            except: pass
        it.reference.delete()
    # borrar adjuntos
    for a in ag_doc.reference.collection("attachments").stream():
        ad = a.to_dict()
        try: bucket.blob(ad.get("path","")).delete()
        except: pass
        a.reference.delete()
    ag_doc.reference.delete()
