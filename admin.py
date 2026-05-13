import os

import streamlit as st

import db

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "05081991")
ATTR_TYPES = ["scale", "select", "multiselect", "text"]


def check_auth() -> bool:
    if st.session_state.get("authenticated"):
        return True
    st.title("🔐 Tasting Tool — Admin")
    pwd = st.text_input("Password", type="password")
    if st.button("Log in", type="primary"):
        if pwd == ADMIN_PASSWORD:
            st.session_state["authenticated"] = True
            st.rerun()
        else:
            st.error("Wrong password.")
    return False


def render_admin() -> None:
    if not check_auth():
        return

    st.sidebar.title("🥤 Tasting Tool")
    st.sidebar.caption("Admin console")
    if st.sidebar.button("Log out"):
        st.session_state["authenticated"] = False
        st.rerun()

    tab_products, tab_sessions, tab_results = st.tabs(
        ["Products & attributes", "Sessions", "Results"]
    )
    with tab_products:
        render_products_tab()
    with tab_sessions:
        render_sessions_tab()
    with tab_results:
        render_results_tab()


# ── Products tab ─────────────────────────────────────────────────────────────

def render_products_tab() -> None:
    st.subheader("Products")
    st.caption("A product defines the set of attributes tasters rate.")

    products = db.list_products()

    with st.expander("➕ Add new product"):
        new_name = st.text_input("Product name", key="np_name", placeholder="e.g. Mushroom Coffee")
        new_cat = st.text_input("Category", key="np_cat", placeholder="e.g. coffee / cocoa / creamer")
        if st.button("Create product", key="np_btn", type="primary"):
            if new_name.strip():
                try:
                    db.create_product(new_name.strip(), new_cat.strip() or None)
                    st.success(f"Created '{new_name}'.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Failed: {e}")
            else:
                st.error("Name required.")

    if not products:
        st.info("No products yet — create one above.")
        return

    names = [p["name"] for p in products]
    selected_name = st.selectbox("Edit product", names, key="prod_select")
    product = next(p for p in products if p["name"] == selected_name)

    with st.expander("✏️ Edit / delete product"):
        ed_name = st.text_input("Name", value=product["name"], key=f"ep_n_{product['id']}")
        ed_cat = st.text_input("Category", value=product["category"] or "", key=f"ep_c_{product['id']}")
        c1, c2 = st.columns(2)
        if c1.button("💾 Save", key=f"ep_save_{product['id']}"):
            db.update_product(product["id"], ed_name.strip(), ed_cat.strip() or None)
            st.success("Saved.")
            st.rerun()
        if c2.button("🗑️ Delete product (and its sessions/responses)", key=f"ep_del_{product['id']}"):
            db.delete_product(product["id"])
            st.success("Deleted.")
            st.rerun()

    st.markdown(f"### Attributes for *{product['name']}*")
    st.caption("These are the questions tasters answer for each sample.")
    attrs = db.list_attributes(product["id"])

    for attr in attrs:
        label = f"{attr['display_order']}. {attr['name']}  —  *{attr['type']}*"
        with st.expander(label):
            render_attribute_editor(attr)

    with st.expander("➕ Add new attribute"):
        render_attribute_creator(product["id"], len(attrs) + 1)


def render_attribute_editor(attr) -> None:
    name = st.text_input("Name", value=attr["name"], key=f"ea_n_{attr['id']}")
    type_ = st.selectbox(
        "Type",
        ATTR_TYPES,
        index=ATTR_TYPES.index(attr["type"]),
        key=f"ea_t_{attr['id']}",
        help="scale = numeric slider · select = one choice · multiselect = many · text = free text",
    )
    order = st.number_input(
        "Display order", value=int(attr["display_order"]), step=1, key=f"ea_o_{attr['id']}"
    )
    config = dict(attr["config"] or {})
    description = st.text_input(
        "Help text (optional)",
        value=config.get("description", ""),
        key=f"ea_d_{attr['id']}",
        help="Shown to tasters below the question, e.g. 'Just-About-Right scale — 3 means perfectly balanced.'",
    )

    if type_ == "scale":
        c1, c2 = st.columns(2)
        config["min"] = int(c1.number_input("Min", value=int(config.get("min", 1)), step=1, key=f"ea_mn_{attr['id']}"))
        config["max"] = int(c2.number_input("Max", value=int(config.get("max", 10)), step=1, key=f"ea_mx_{attr['id']}"))
        c1, c2 = st.columns(2)
        config["low_label"] = c1.text_input("Low-end label", value=config.get("low_label", ""), key=f"ea_ll_{attr['id']}")
        config["high_label"] = c2.text_input("High-end label", value=config.get("high_label", ""), key=f"ea_hl_{attr['id']}")
    elif type_ in ("select", "multiselect"):
        opts_str = st.text_area(
            "Options (one per line)",
            value="\n".join(config.get("options", [])),
            key=f"ea_op_{attr['id']}",
        )
        config["options"] = [o.strip() for o in opts_str.split("\n") if o.strip()]
    else:
        config = {}

    if description.strip():
        config["description"] = description.strip()

    c1, c2 = st.columns(2)
    if c1.button("💾 Save", key=f"ea_save_{attr['id']}", type="primary"):
        db.update_attribute(attr["id"], name.strip(), type_, config, int(order))
        st.success("Saved.")
        st.rerun()
    if c2.button("🗑️ Delete attribute", key=f"ea_del_{attr['id']}"):
        db.delete_attribute(attr["id"])
        st.rerun()


def render_attribute_creator(product_id, default_order) -> None:
    name = st.text_input("Name", key=f"na_n_{product_id}", placeholder="e.g. Aroma intensity")
    type_ = st.selectbox(
        "Type",
        ATTR_TYPES,
        key=f"na_t_{product_id}",
        help="scale = numeric slider · select = one choice · multiselect = many · text = free text",
    )
    order = st.number_input("Display order", value=int(default_order), step=1, key=f"na_o_{product_id}")
    description = st.text_input(
        "Help text (optional)",
        key=f"na_d_{product_id}",
        placeholder="Shown under the question to tasters",
    )
    config = {}
    if type_ == "scale":
        c1, c2 = st.columns(2)
        config["min"] = int(c1.number_input("Min", value=1, step=1, key=f"na_mn_{product_id}"))
        config["max"] = int(c2.number_input("Max", value=10, step=1, key=f"na_mx_{product_id}"))
        c1, c2 = st.columns(2)
        config["low_label"] = c1.text_input("Low-end label", key=f"na_ll_{product_id}", placeholder="e.g. weak")
        config["high_label"] = c2.text_input("High-end label", key=f"na_hl_{product_id}", placeholder="e.g. strong")
    elif type_ in ("select", "multiselect"):
        opts_str = st.text_area("Options (one per line)", key=f"na_op_{product_id}")
        config["options"] = [o.strip() for o in opts_str.split("\n") if o.strip()]

    if description.strip():
        config["description"] = description.strip()

    if st.button("➕ Add attribute", key=f"na_btn_{product_id}", type="primary"):
        if not name.strip():
            st.error("Name required.")
        else:
            db.create_attribute(product_id, name.strip(), type_, config, int(order))
            st.rerun()


# ── Sessions tab ─────────────────────────────────────────────────────────────

def render_sessions_tab() -> None:
    st.subheader("Sessions")
    products = db.list_products()
    if not products:
        st.warning("Create a product first (with at least one attribute).")
        return

    with st.expander("➕ Start a new tasting session", expanded=False):
        render_session_creator(products)

    sessions = db.list_sessions()
    if not sessions:
        st.info("No sessions yet.")
        return

    st.markdown("### All sessions")
    for sess in sessions:
        status_emoji = "🟢" if sess["status"] == "open" else "🔒"
        header = (
            f"{status_emoji} **{sess['name']}** · {sess['product_name']} · "
            f"{sess['response_count']} responses from {sess['taster_count']} tasters"
        )
        with st.expander(header):
            render_session_row(sess)


def render_session_creator(products) -> None:
    name = st.text_input(
        "Session name (shown to tasters)",
        key="ns_name",
        placeholder="e.g. Coffee batch comparison",
    )
    prod_options = {p["name"]: p["id"] for p in products}
    prod_name = st.selectbox("Product (determines the questions)", list(prod_options.keys()), key="ns_prod")
    num = int(st.number_input("Number of samples", min_value=1, max_value=26, value=3, step=1, key="ns_num"))

    st.caption(
        "Sample identity mapping (**admin-only — never shown to tasters**). "
        "Tasters see only 'Sample A', 'Sample B', etc."
    )
    mapping = {}
    for i in range(num):
        L = chr(ord("A") + i)
        mapping[L] = st.text_input(
            f"Sample {L} =",
            key=f"ns_map_{L}",
            placeholder="e.g. Batch 47 dark roast",
        )

    if st.button("🚀 Create session", key="ns_btn", type="primary"):
        if not name.strip():
            st.error("Session name required.")
        else:
            sid, token = db.create_session(name.strip(), prod_options[prod_name], num, mapping)
            st.session_state["just_created_token"] = token
            st.success("Session created — share link is in the list below.")
            st.rerun()


def render_session_row(sess) -> None:
    base_url = os.environ.get("APP_URL", "http://localhost:8501")
    share_url = f"{base_url}/?session={sess['share_token']}"
    st.markdown("**Share this link with tasters:**")
    st.code(share_url, language=None)

    if sess["sample_mapping"]:
        with st.expander("🔑 Sample identities (admin only)", expanded=False):
            for L, identity in sess["sample_mapping"].items():
                st.markdown(f"- **Sample {L}** → {identity or '_unspecified_'}")

    c1, c2, c3 = st.columns(3)
    if sess["status"] == "open":
        if c1.button("🏁 Finish testing", key=f"close_{sess['id']}", type="primary"):
            db.close_session(sess["id"])
            st.success("Session closed — see Results tab.")
            st.rerun()
    else:
        if c1.button("🔓 Reopen", key=f"reopen_{sess['id']}"):
            db.reopen_session(sess["id"])
            st.rerun()
    if c3.button("🗑️ Delete session", key=f"del_{sess['id']}"):
        db.delete_session(sess["id"])
        st.rerun()


# ── Results tab ──────────────────────────────────────────────────────────────

def render_results_tab() -> None:
    st.subheader("Results")
    sessions = db.list_sessions()
    if not sessions:
        st.info("No sessions to analyze yet.")
        return

    options = {
        f"{'🟢' if s['status']=='open' else '🔒'}  {s['name']}  ·  {s['product_name']}  ({s['response_count']} resp.)": s["id"]
        for s in sessions
    }
    label = st.selectbox("Pick a session", list(options.keys()), key="res_select")
    sid = options[label]

    from analytics import render_analytics

    render_analytics(sid)
