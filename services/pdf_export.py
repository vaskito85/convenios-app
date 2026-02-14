import io
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.utils import ImageReader

def build_agreement_pdf(db, bucket, ag_doc, leyenda=""):
    ag = ag_doc.to_dict()
    items = list(ag_doc.reference.collection("installments").order_by("number").stream())
    rows = [["Nº","Vencimiento","Capital","Interés","Total"]]
    sum_cap = sum(float(it.to_dict()["capital"]) for it in items)
    sum_int = sum(float(it.to_dict()["interest"]) for it in items)
    sum_tot = sum(float(it.to_dict()["total"]) for it in items)
    for it in items:
        d = it.to_dict()
        rows.append([
            str(d["number"]), d["due_date"],
            f"${d['capital']:,.2f}", f"${d['interest']:,.2f}", f"${d['total']:,.2f}"
        ])
    rows.append(["","TOTAL", f"${sum_cap:,.2f}", f"${sum_int:,.2f}", f"${sum_tot:,.2f}"])
    atts = list(ag_doc.reference.collection("attachments").stream())
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=2*cm, rightMargin=2*cm, topMargin=2*cm, bottomMargin=2*cm)
    story=[]
    styles=getSampleStyleSheet()
    story.append(Paragraph(f"Convenio #{ag_doc.id}", styles["Title"]))
    story.append(Spacer(1,0.2*cm))
    story.append(Paragraph(f"Cliente: {ag.get('client_email','')}", styles["Normal"]))
    story.append(Paragraph(f"Operador: {ag.get('operator_id','')}", styles["Normal"]))
    story.append(Paragraph(f"Título: {ag.get('title','')}", styles["Normal"]))
    story.append(Paragraph(f"Notas: {ag.get('notes','') or '-'}", styles["Normal"]))
    story.append(Paragraph(f"Principal: ${ag['principal']:,.2f}", styles["Normal"]))
    story.append(Paragraph(f"Interés mensual aplicado: {ag['interest_rate']*100:.2f}%", styles["Normal"]))
    story.append(Paragraph(f"Cuotas: {ag['installments']} — Método: {ag['method']}", styles["Normal"]))
    story.append(Paragraph(f"Inicio: {ag.get('start_date','')}", styles["Normal"]))
    story.append(Spacer(1,0.5*cm))
    # Leyenda de convenio finalizado
    if leyenda:
        story.append(Paragraph(f"{leyenda}", styles["Heading2"]))
        story.append(Spacer(1,0.3*cm))
    story.append(Paragraph("Calendario de cuotas", styles["Heading2"]))
    tbl = Table(rows)
    tbl.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,0),colors.lightgrey),
        ("GRID",(0,0),(-1,-1),0.25,colors.grey),
        ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),
        ("FONTNAME",(1,-1),(-1,-1),"Helvetica-Bold"),
    ]))
    story.append(tbl)
    story.append(Spacer(1,0.5*cm))
    story.append(Paragraph("Documentación adjunta", styles["Heading2"]))
    if not atts:
        story.append(Paragraph("No hay adjuntos.", styles["Normal"]))
    else:
        for a in atts:
            ad=a.to_dict()
            story.append(Paragraph(f"- {ad.get('name')} ({ad.get('content_type','')})", styles["Normal"]))
            ctype = (ad.get("content_type") or "").lower()
            if ctype.startswith("image/"):
                try:
                    blob = bucket.blob(ad["path"])
                    img_bytes = blob.download_as_bytes()
                    img = Image(ImageReader(io.BytesIO(img_bytes)))
                    img._restrictSize(14*cm,10*cm)
                    story.append(Spacer(1,0.2*cm)); story.append(img); story.append(Spacer(1,0.2*cm))
                except Exception:
                    pass
    doc.build(story)
    pdf = buf.getvalue(); buf.close()
    return pdf
