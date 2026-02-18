import streamlit as st
from services.agreements import list_agreements_for_role, delete_agreement
from services.installments import mark_paid, mark_unpaid
from core.firebase import get_bucket
from services.pdf_export import build_agreement_pdf
from core.mail import send_email
from services.notifications import (
    notify_agreement_sent,
    notify_agreement_accepted,
    notify_agreement_rejected
)
from services.cloudinary_upload import upload_to_cloudinary
from datetime import datetime

def render(db, user):
    st.subheader("📄 Mis convenios")
    ags = list_agreements_for_role(db, user)
    if not ags:
        st.info("No tenés convenios todavía."); return

    for ag_doc in ags:
        ag = ag_doc.to_dict()
        items = list(ag_doc.reference.collection("installments").order_by("number").stream())
        pagas = sum(1 for inst in items if inst.to_dict().get("paid"))
        impagas = len(items) - pagas
        estado = ag.get("status", "DRAFT")
        fecha_inicio = ag.get("start_date", "-")
        fechas = [inst.to_dict().get("due_date") for inst in items]
        proxima = next((f for f, inst in zip(fechas, items) if not inst.to_dict().get("paid")), "-")
        ultima = fechas[-1] if fechas else "-"
        nombre_cliente = ag.get("client_name", ag.get("client_email", ""))
        fecha = ag.get("created_at")
        if hasattr(fecha, "strftime"):
            fecha_str = fecha.strftime("%Y_%m_%d")
        elif isinstance(fecha, str):
            fecha_str = fecha.split("T")[0].replace("-", "_")
        else:
            fecha_str = "fecha"
        nombre_convenio = f"{nombre_cliente}_{fecha_str}"

        icono_estado = {
            "DRAFT": "📝",
            "PENDING_ACCEPTANCE": "⏳",
            "ACTIVE": "✅",
            "COMPLETED": "🏁",
            "REJECTED": "❌"
        }.get(estado, "📄")
        badge_color = {
            "DRAFT": "#888",
            "PENDING_ACCEPTANCE": "#ff9800",
            "ACTIVE": "#2e7d32",
            "COMPLETED": "#1976d2",
            "REJECTED": "#c62828"
        }.get(estado, "#888")

        # --- Bloque visual de estado mejorado (modo oscuro y claro) ---
        bg_block = "#222"  # Fondo oscuro
        text_block = "#fff"  # Letras claras
        st.markdown(
            f"""
            <div style="border:2px solid {badge_color};background:{bg_block};padding:16px 12px 12px 12px;margin-bottom:8px;border-radius:12px;display:flex;align-items:center;">
                <span style="font-size:1.3em;font-weight:bold;margin-right:12px;color:{badge_color};">{icono_estado}</span>
                <span style="font-size:1.15em;font-weight:bold;color:{text_block};">{nombre_convenio}</span>
                <span style="margin-left:auto;font-size:1.1em;font-weight:bold;color:{badge_color};background:{bg_block};padding:4px 12px;border-radius:8px;border:1.5px solid {badge_color};">{estado}</span>
            </div>
            """, unsafe_allow_html=True
        )

        # --- Resumen visual debajo del bloque de estado ---
        st.markdown(
            f"""
            <div style="border:1px solid #444;padding:8px;margin-bottom:4px;border-radius:6px;background:#282828;color:#fff;">
            Cuotas pagas: <b>{pagas}</b> | Cuotas impagas: <b>{impagas}</b><br>
            Inicio: <b>{fecha_inicio}</b> | Próxima cuota: <b>{proxima}</b> | Última cuota: <b>{ultima}</b>
            </div>
            """, unsafe_allow_html=True
        )

        with st.expander(f"{nombre_convenio}"):
            # Si el cliente rechazó el convenio, mostrar solo el estado y motivo
            if user.get("role") == "cliente" and ag.get("status") == "REJECTED":
                st.markdown(
                    f"""
                    <div style="border:1px solid #c62828;padding:12px;margin-bottom:8px;border-radius:10px;background:#2a2a2a;color:#fff;">
                    <span style="font-size:1.1em;font-weight:bold;color:#c62828;">❌ Convenio rechazado</span><br>
                    <span style="font-size:0.97em;">Motivo: <b>{ag.get('rejection_note','(sin motivo)')}</b></span>
                    </div>
                    """, unsafe_allow_html=True
                )
                continue  # No mostrar nada más para este convenio

            # OPERADOR: enviar a aprobación si está en DRAFT
            if user.get("role") == "operador" and ag.get("status") == "DRAFT":
                if st.button("Enviar a aprobación", key=f"aprobacion_{ag_doc.id}"):
                    ag_doc.reference.update({"status": "PENDING_ACCEPTANCE"})
                    notify_agreement_sent(st, db, ag_doc)
                    st.success("Convenio enviado a aprobación.")
                    st.rerun()
            # OPERADOR: finalizar convenio y enviar PDF
            if user.get("role")=="operador" and pagas == len(items) and ag.get("status") != "COMPLETED":
                if st.button("Finalizar convenio y enviar PDF", key=f"finalizar_{ag_doc.id}"):
                    bucket = get_bucket()
                    pdf_bytes = build_agreement_pdf(db, bucket, ag_doc, leyenda="Convenio finalizado")
                    operador_email = ag.get("operator_email") or user.get("email")
                    cliente_email = ag.get("client_email")
                    asunto = f"{nombre_convenio} finalizado"
                    html = f"<h4>Convenio finalizado</h4><p>Adjunto PDF con todas las cuotas pagas.</p>"
                    send_email(operador_email, asunto, html, attachments=[(f"{nombre_convenio}.pdf", pdf_bytes, "application/pdf")])
                    send_email(cliente_email, asunto, html, attachments=[(f"{nombre_convenio}.pdf", pdf_bytes, "application/pdf")])
                    st.success("PDF generado y enviado por email al operador y cliente.")
            # CLIENTE: aceptar o rechazar convenio si está en PENDING_ACCEPTANCE
            if user.get("role") == "cliente" and ag.get("status") == "PENDING_ACCEPTANCE":
                col1, col2 = st.columns(2)
                if col1.button("Aceptar convenio", key=f"aceptar_{ag_doc.id}"):
                    ag_doc.reference.update({"status": "ACTIVE", "accepted_at": st.session_state.get("now")})
                    notify_agreement_accepted(st, db, ag_doc)
                    st.success("Convenio aceptado.")
                    st.rerun()
                motivo_rechazo = col2.text_input("Motivo rechazo (opcional)", key=f"motivo_{ag_doc.id}")
                if col2.button("Rechazar convenio", key=f"rechazar_{ag_doc.id}"):
                    ag_doc.reference.update({"status": "REJECTED", "rejection_note": motivo_rechazo})
                    notify_agreement_rejected(st, db, ag_doc.reference, motivo_rechazo)
                    st.warning("Convenio rechazado.")
                    st.rerun()
            # ADMIN: eliminar convenio
            if user.get("role") == "admin":
                if st.button("❌ Eliminar convenio", key=f"del_ag_{ag_doc.id}"):
                    bucket = get_bucket()
                    delete_agreement(db, bucket, ag_doc)
                    st.warning("Convenio eliminado.")
                    st.rerun()
            # --- CONTENIDO DEL CONVENIO ---
            st.write(f"Estado: {ag.get('status','DRAFT')}")
            for inst in items:
                d = inst.to_dict()
                color_bg = "#282828" if d.get("paid") else "#2a2a2a"
                color_title = "#2e7d32" if d.get("paid") else "#c62828"
                estado_cuota = "Pagada" if d.get("paid") else "Impaga"
                icono_cuota = "✔️" if d.get("paid") else "⏳"
                text_color = "#fff"
                st.markdown(
                    f"""
                    <div style="background:{color_bg};border:1.5px solid #444;padding:12px;margin-bottom:10px;border-radius:10px;">
                    <span style="font-size:1.1em;font-weight:bold;color:{color_title};">{icono_cuota} Cuota {d['number']}</span>
                    <span style="float:right;color:{color_title};font-weight:bold;">{estado_cuota}</span><br>
                    <span style="font-size:0.97em;color:{text_color};">Vencimiento: <b>{d['due_date']}</b> | Total: <b>${d['total']:,.2f}</b></span>
                    </div>
                    """, unsafe_allow_html=True
                )
                # Botones y acciones
                if user.get("role")=="operador" and not d.get("paid"):
                    colA, colB = st.columns(2)
                    if colA.button(f"Marcar pagada cuota {d['number']} (manual)", key=f"paid_{inst.id}"):
                        mark_paid(inst.reference, manual_note="Marcada manualmente por operador")
                        st.success("✔️ Cuota marcada como pagada.")
                        st.rerun()
                if d.get("paid") and user.get("role") in ["operador", "admin"]:
                    if st.button(f"Revertir cuota {d['number']}", key=f"unpaid_{inst.id}"):
                        mark_unpaid(inst.reference)
                        st.warning("⏪ Cuota revertida a impaga.")
                        st.rerun()
                if user.get("role") == "cliente" and not d.get("paid") and d.get("receipt_status") not in ["PENDING", "APPROVED", "REJECTED"]:
                    st.markdown("**¿Pagaste esta cuota?**")
                    comprobante = st.file_uploader(
                        f"Subí tu comprobante para cuota {d['number']} (PDF/JPG/PNG)", 
                        type=["pdf", "jpg", "jpeg", "png"], 
                        key=f"comprobante_{inst.id}"
                    )
                    nota_cliente = st.text_input("Nota para el operador (opcional)", key=f"nota_{inst.id}")
                    if st.button(f"Declarar pago cuota {d['number']}", key=f"declarar_pago_{inst.id}"):
                        url_comprobante = None
                        if comprobante is not None:
                            url_comprobante = upload_to_cloudinary(comprobante, comprobante.name)
                        inst.reference.update({
                            "receipt_status": "PENDING",
                            "receipt_url": url_comprobante,
                            "receipt_note": nota_cliente,
                            "paid": False
                        })
                        st.success("¡Pago declarado correctamente! El operador recibirá tu comprobante y te notificará cuando lo apruebe o rechace.")
                        st.rerun()
                if user.get("role") == "operador" and d.get("receipt_url"):
                    st.markdown(f"{d['receipt_url']}")
