from collections import Counter

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import db


def render_analytics(session_id: int) -> None:
    sess = db.get_session(session_id)
    if not sess:
        st.error("Session not found.")
        return

    attrs = db.list_attributes(sess["product_id"])
    responses = db.list_responses(session_id)

    status_emoji = "🟢 Open" if sess["status"] == "open" else "🔒 Closed"
    st.markdown(f"### {sess['name']}")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Status", status_emoji)
    c2.metric("Samples", sess["num_samples"])
    c3.metric("Unique tasters", len({r["taster_name"] for r in responses}))
    c4.metric("Total responses", len(responses))

    sample_labels = [chr(ord("A") + i) for i in range(sess["num_samples"])]

    if sess["sample_mapping"]:
        with st.expander("🔑 Sample identity (admin only)", expanded=True):
            map_rows = [
                {"Sample": L, "Identity": sess["sample_mapping"].get(L) or "—"}
                for L in sample_labels
            ]
            st.dataframe(pd.DataFrame(map_rows), use_container_width=True, hide_index=True)

    if not responses:
        st.info("No responses yet. Share the link to start collecting answers.")
        return

    df = _build_dataframe(responses, attrs)
    df = df.sort_values("submitted_at").drop_duplicates(["taster", "sample"], keep="last")

    present_samples = sorted(df["sample"].unique())
    scale_attrs = [a for a in attrs if a["type"] == "scale"]
    select_attrs = [a for a in attrs if a["type"] == "select"]
    multi_attrs = [a for a in attrs if a["type"] == "multiselect"]
    text_attrs = [a for a in attrs if a["type"] == "text"]

    if scale_attrs:
        _render_scale_table(df, scale_attrs, present_samples)
        if len(scale_attrs) >= 3:
            _render_radar(df, scale_attrs, present_samples)
        _render_ranking(df, scale_attrs, present_samples, sess["sample_mapping"])

    for a in select_attrs:
        _render_select_breakdown(df, a, present_samples)

    for a in multi_attrs:
        _render_multiselect_breakdown(df, a, present_samples)

    for a in text_attrs:
        _render_text_notes(df, a, present_samples)

    with st.expander("📋 Raw responses"):
        st.dataframe(df, use_container_width=True)
        csv = df.to_csv(index=False).encode("utf-8")
        safe_name = "".join(c if c.isalnum() else "_" for c in sess["name"])
        st.download_button(
            "⬇️ Download CSV",
            csv,
            file_name=f"tasting_{safe_name}.csv",
            mime="text/csv",
        )


def _build_dataframe(responses, attrs) -> pd.DataFrame:
    rows = []
    for r in responses:
        row = {
            "taster": r["taster_name"],
            "sample": r["sample_label"],
            "submitted_at": r["submitted_at"],
        }
        for a in attrs:
            row[a["name"]] = r["answers"].get(str(a["id"]))
        rows.append(row)
    return pd.DataFrame(rows)


def _render_scale_table(df, scale_attrs, samples) -> None:
    st.markdown("#### Numeric scores — mean ± std (n)")
    agg_rows = []
    for a in scale_attrs:
        row = {"Attribute": a["name"]}
        for s in samples:
            vals = pd.to_numeric(df[df["sample"] == s][a["name"]], errors="coerce").dropna()
            if len(vals):
                std = vals.std() if len(vals) > 1 else 0.0
                row[f"Sample {s}"] = f"{vals.mean():.2f} ± {std:.2f}  (n={len(vals)})"
            else:
                row[f"Sample {s}"] = "—"
        agg_rows.append(row)
    st.dataframe(pd.DataFrame(agg_rows), use_container_width=True, hide_index=True)


def _render_radar(df, scale_attrs, samples) -> None:
    st.markdown("#### Radar comparison")
    fig = go.Figure()
    categories = [a["name"] for a in scale_attrs]
    for s in samples:
        means = []
        for a in scale_attrs:
            vals = pd.to_numeric(df[df["sample"] == s][a["name"]], errors="coerce").dropna()
            means.append(float(vals.mean()) if len(vals) else 0.0)
        fig.add_trace(
            go.Scatterpolar(
                r=means + [means[0]],
                theta=categories + [categories[0]],
                fill="toself",
                name=f"Sample {s}",
            )
        )
    fig.update_layout(
        polar=dict(radialaxis=dict(visible=True)),
        showlegend=True,
        height=500,
        margin=dict(l=40, r=40, t=20, b=40),
    )
    st.plotly_chart(fig, use_container_width=True)


def _render_ranking(df, scale_attrs, samples, mapping) -> None:
    st.markdown("#### Overall ranking")
    st.caption("Average of all numeric attributes per sample.")
    rank_rows = []
    for s in samples:
        sub = df[df["sample"] == s]
        all_vals = []
        for a in scale_attrs:
            all_vals.extend(pd.to_numeric(sub[a["name"]], errors="coerce").dropna().tolist())
        if all_vals:
            mean = sum(all_vals) / len(all_vals)
            rank_rows.append(
                {
                    "Sample": s,
                    "Identity": mapping.get(s) or "—",
                    "Overall avg": round(mean, 2),
                    "n scores": len(all_vals),
                }
            )
    if rank_rows:
        rank_df = pd.DataFrame(rank_rows).sort_values("Overall avg", ascending=False).reset_index(drop=True)
        rank_df.insert(0, "Rank", range(1, len(rank_df) + 1))
        st.dataframe(rank_df, use_container_width=True, hide_index=True)


def _render_select_breakdown(df, attr, samples) -> None:
    st.markdown(f"#### {attr['name']}  · single choice")
    sub = df[["sample", attr["name"]]].dropna()
    if sub.empty:
        st.caption("_No answers yet._")
        return
    counts = sub.groupby(["sample", attr["name"]]).size().reset_index(name="count")
    pivot = counts.pivot(index=attr["name"], columns="sample", values="count").fillna(0).astype(int)
    pivot.columns = [f"Sample {c}" for c in pivot.columns]
    st.dataframe(pivot, use_container_width=True)


def _render_multiselect_breakdown(df, attr, samples) -> None:
    st.markdown(f"#### {attr['name']}  · multiple choice")
    rows = []
    for s in samples:
        c = Counter()
        for v in df[df["sample"] == s][attr["name"]]:
            if isinstance(v, list):
                c.update(v)
        for opt, n in c.items():
            rows.append({"Sample": f"Sample {s}", "Option": opt, "Count": n})
    if not rows:
        st.caption("_No answers yet._")
        return
    pivot = (
        pd.DataFrame(rows)
        .pivot(index="Option", columns="Sample", values="Count")
        .fillna(0)
        .astype(int)
    )
    st.dataframe(pivot, use_container_width=True)


def _render_text_notes(df, attr, samples) -> None:
    st.markdown(f"#### {attr['name']}  · free-text notes")
    for s in samples:
        with st.expander(f"Sample {s}"):
            sub = df[df["sample"] == s][["taster", attr["name"]]].dropna()
            sub = sub[sub[attr["name"]].astype(str).str.strip() != ""]
            if sub.empty:
                st.caption("_No notes._")
            else:
                for _, row in sub.iterrows():
                    st.markdown(f"**{row['taster']}:** {row[attr['name']]}")
