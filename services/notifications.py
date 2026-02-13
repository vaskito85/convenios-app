from core.mail import send_email, send_email_admins

def _base_url(st):
    try:
        return st.secrets.get("APP_BASE_URL","https://example.com")
    except Exception:
        return "https://example.com"

def notify_agreement_sent(st, db, ag_ref):
    ag = ag_ref.get().to_dict()
    base = _base_url(st)
    subject = f"Convenio enviado para aceptación (#{ag_ref.id})"
    html = f"""
#### Convenio #{ag_ref.id} enviado

Cliente: {ag.get('client_email','')}
Monto: ${ag['principal']:,.2f}
Interés: {ag['interest_rate']*100:.2f}%
Cuotas: {ag['installments']}
Ingresá a la app para revisarlo y aceptarlo: {base}
"""
    op = db.collection("users").document(ag["operator_id"]).get().to_dict()
    for to in {op.get("email"), ag.get("client_email")}:
        if to: send_email(to, subject, html)
    send_email_admins("Nuevo convenio creado",
                      f"#### Nuevo convenio creado\n\nConvenio #{ag_ref.id}\nOperador: {op.get('email')}\nCliente: {ag.get('client_email')}\nAcceso: {base}")

def notify_agreement_accepted(st, db, ag_ref):
    ag = ag_ref.get().to_dict()
    base = _base_url(st)
    subject = f"Convenio aceptado (#{ag_ref.id})"
    html = f"""
#### Convenio #{ag_ref.id} aceptado

Cliente: {ag.get('client_email','')}
El convenio fue aceptado y está activo.
Acceso: {base}
"""
    op = db.collection("users").document(ag["operator_id"]).get().to_dict()
    for to in {op.get("email"), ag.get("client_email")}:
        if to: send_email(to, subject, html)

def notify_agreement_rejected(st, db, ag_ref, note):
    ag = ag_ref.get().to_dict()
    base = _base_url(st)
    subject = f"Convenio rechazado (#{ag_ref.id})"
    html = f"""
#### Convenio #{ag_ref.id} rechazado

Cliente: {ag.get('client_email','')}
Motivo: {note}
Acceso: {base}
"""
    op = db.collection("users").document(ag["operator_id"]).get().to_dict()
    for to in {op.get("email"), ag.get("client_email")}:
        if to: send_email(to, subject, html)

def notify_operator_new_receipt(st, db, ag_doc, inst_num, user_email):
    base = _base_url(st)
    op = db.collection("users").document(ag_doc.to_dict()["operator_id"]).get().to_dict()
    send_email(op.get("email"), "Nuevo comprobante/pago declarado",
               f"#### Nuevo comprobante/pago declarado\n\nConvenio #{ag_doc.id} - Cuota {inst_num}\nDeclarado por: {user_email}\nAcceso: {base}")

def notify_client_receipt_decision(st, db, ag_doc, inst_num, decision, note):
    base = _base_url(st)
    ag = ag_doc.to_dict()
    email = ag.get("client_email")
    if ag.get("client_id"):
        cl = db.collection("users").document(ag["client_id"]).get().to_dict()
        email = (cl or {}).get("email") or email
    send_email(email, "Resultado de verificación de pago",
               f"#### Resultado de verificación de pago\n\nConvenio #{ag_doc.id} - Cuota {inst_num}\nEstado: **{decision}**\nDetalle: {note or '(sin detalle)'}\nAcceso: {base}")
