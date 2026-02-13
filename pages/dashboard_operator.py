import streamlit as st

def render(db, user):
    st.subheader("📈 Mi panel (operador)")
    ags = list(db.collection("agreements").where("operator_id","==",user["uid"]).stream())
    if not ags:
        st.info("No tenés convenios todavía."); return
    states = {"DRAFT":0,"PENDING_ACCEPTANCE":0,"ACTIVE":0,"COMPLETED":0,"CANCELLED":0,"REJECTED":0}
    for a in ags:
        states[a.to_dict().get("status","DRAFT")] += 1
    st.write("### Mis convenios")
    def colorize(s):
        if s=="PENDING_ACCEPTANCE": return ":orange[PENDING_ACCEPTANCE]"
        if s=="REJECTED": return ":red[REJECTED]"
        if s in {"ACTIVE","COMPLETED"}: return f":green[{s}]"
        if s=="CANCELLED": return ":gray[CANCELLED]"
        return s
    for k,v in states.items():
        st.markdown(f"- {colorize(k)}: **{v}**")
