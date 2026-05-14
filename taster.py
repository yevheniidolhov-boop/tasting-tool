import streamlit as st

import db


def render_taster(token: str) -> None:
    sess = db.get_session_by_token(token)
    if not sess:
        st.error("This tasting link is invalid or has been deleted.")
        return

    if sess["status"] == "closed":
        st.title("🔒 Tasting closed")
        st.markdown(
            f"**{sess['name']}** is no longer accepting responses. "
            "Thanks for your interest!"
        )
        return

    st.title(f"🥤 {sess['name']}")
    st.markdown(
        "Welcome! Please taste each sample and fill in your impressions below. "
        "_Take your time — there are no wrong answers._"
    )

    if "taster_name" not in st.session_state:
        st.session_state["taster_name"] = ""
    taster_name = st.text_input("Your name", value=st.session_state["taster_name"])
    st.session_state["taster_name"] = taster_name

    if not taster_name.strip():
        st.info("👆 Enter your name to start.")
        return

    sample_labels = [chr(ord("A") + i) for i in range(sess["num_samples"])]
    tab_labels = [db.sample_display_name(sess, L) for L in sample_labels]
    tabs = st.tabs(tab_labels)
    for tab, label, display in zip(tabs, sample_labels, tab_labels):
        with tab:
            product_id = db.get_sample_product_id(sess, label)
            if not product_id:
                st.error(f"Sample {label} has no product assigned. Ask the organizer to fix the session.")
                continue
            sample_attrs = db.list_attributes(product_id)
            if not sample_attrs:
                st.error(f"Sample {label}'s product has no questions configured.")
                continue
            render_sample_form(sess, label, sample_attrs, taster_name.strip(), display)


def render_sample_form(sess, label: str, attrs, taster_name: str, display_name: str) -> None:
    st.markdown(f"### 🍵 {display_name}")
    st.caption("Rate each aspect after tasting this sample.")

    submitted_key = f"submitted_{sess['id']}_{label}_{taster_name}"

    answers = {}
    for a in attrs:
        widget_key = f"a_{sess['id']}_{label}_{a['id']}"
        cfg = a["config"] or {}
        description = (cfg.get("description") or "").strip()

        st.markdown(f"**{a['name']}**")
        if description:
            st.caption(description)

        if a["type"] == "scale":
            mn = int(cfg.get("min", 1))
            mx = int(cfg.get("max", 10))
            if mx <= mn:
                mx = mn + 1
            low = cfg.get("low_label", "")
            high = cfg.get("high_label", "")
            slider_label = f"{low}   ◄    ►   {high}" if (low or high) else " "
            answers[str(a["id"])] = st.slider(
                slider_label,
                min_value=mn,
                max_value=mx,
                value=(mn + mx) // 2,
                key=widget_key,
            )
        elif a["type"] == "select":
            opts = cfg.get("options", [])
            if opts:
                answers[str(a["id"])] = st.radio(
                    a["name"], opts, key=widget_key, label_visibility="collapsed"
                )
            else:
                st.caption("_No options configured._")
                answers[str(a["id"])] = None
        elif a["type"] == "multiselect":
            opts = cfg.get("options", [])
            if opts:
                answers[str(a["id"])] = st.multiselect(
                    a["name"], opts, key=widget_key, label_visibility="collapsed"
                )
            else:
                st.caption("_No options configured._")
                answers[str(a["id"])] = []
        elif a["type"] == "text":
            answers[str(a["id"])] = st.text_area(
                a["name"],
                key=widget_key,
                placeholder="Your answer...",
                label_visibility="collapsed",
            )

        st.write("")

    if st.button(f"✅ Submit", key=f"sub_{sess['id']}_{label}", type="primary"):
        db.save_response(sess["id"], label, taster_name, answers)
        st.session_state[submitted_key] = True
        st.success(f"Thanks! Your rating for {display_name} is recorded.")
        st.balloons()
    elif st.session_state.get(submitted_key):
        st.info(
            f"✓ You've already submitted {display_name}. You can submit again to overwrite — "
            "we'll keep your most recent answer in the analytics."
        )
