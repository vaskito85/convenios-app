from typing import Dict
def get_settings(db) -> Dict:
    doc = db.collection("config").document("settings").get()
    if doc.exists:
        d = doc.to_dict() or {}
        return {"interest_enabled": bool(d.get("interest_enabled", False))}
    return {"interest_enabled": False}

def set_settings(db, interest_enabled: bool):
    db.collection("config").document("settings").set(
        {"interest_enabled": bool(interest_enabled)}, merge=True
    )
