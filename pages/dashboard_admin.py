import streamlit as st

def render(db):
    st.subheader("📊 Panel (admin)")
    states = ["DRAFT","PENDING_ACCEPTANCE","ACTIVE","COMPLETED","CANCELLED","REJECTED"]
    counts = {s:0 for s in states}
    ags = list(db.collection("agreements").stream())
    for a in ags:
        s = a.to_dict().get("status","DRAFT")
        counts[s] = counts.get(s,0)+1
    st.write("### Estados de convenios")
    def colorize(s):
        if s=="PENDING_ACCEPTANCE": return ":orange[PENDING_ACCEPTANCE]"
        if s=="REJECTED": return ":red[REJECTED]"
        if s in {"ACTIVE","COMPLETED"}: return f":green[{s}]"
        if s=="CANCELLED": return ":gray[CANCELLED]"
        return s
    for s in states:
        st.markdown(f"- {colorize(s)}: **{counts[s]}**")

    total_sent = counts["PENDING_ACCEPTANCE"]+counts["ACTIVE"]+counts["COMPLETED"]
    accepted = counts["ACTIVE"]+counts["COMPLETED"]
    rate = (accepted/total_sent*100) if total_sent else 0
    st.write(f"**Tasa aceptación**: {rate:.1f}%")
