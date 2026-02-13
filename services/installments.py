from datetime import date
from google.cloud import firestore as gcf
from core import calc

def generate_schedule(db, ag_ref):
    ag = ag_ref.get().to_dict()
    for it in ag_ref.collection("installments").stream():
        it.reference.delete()
    if ag["method"] == "declining":
        items = calc.schedule_declining(ag["principal"], ag["interest_rate"], ag["installments"], date.fromisoformat(ag["start_date"]))
    else:
        items = calc.schedule_french(ag["principal"], ag["interest_rate"], ag["installments"], date.fromisoformat(ag["start_date"]))
    batch = db.batch()
    for it in items:
        doc_ref = ag_ref.collection("installments").document()
        batch.set(doc_ref, {**it, "paid": False, "paid_at": None,
                            "last_reminder_sent": None,
                            "receipt_status": None, "receipt_url": None, "receipt_note": None})
    batch.commit()

def mark_paid(inst_ref, manual_note: str = None):
    inst_ref.update({
        "paid": True,
        "paid_at": gcf.SERVER_TIMESTAMP,
        "receipt_status": "APPROVED" if not inst_ref.get().to_dict().get("receipt_status") else inst_ref.get().to_dict().get("receipt_status"),
        "receipt_note": manual_note
    })

def mark_unpaid(inst_ref):
    inst_ref.update({"paid": False, "paid_at": None})

def auto_complete_if_all_paid(db, ag_doc):
    items = list(ag_doc.reference.collection("installments").stream())
    if items and all(it.to_dict().get("paid") for it in items):
        ag_doc.reference.update({"status":"COMPLETED","completed_at":gcf.SERVER_TIMESTAMP})
        return True
    return False
