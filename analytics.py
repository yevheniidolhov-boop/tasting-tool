import io
from collections import Counter, OrderedDict

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import db


def render_analytics(session_id: int) -> None:
    sess = db.get_session(session_id)
    if not sess:
        st.error("Session not found.")
        return

    sample_labels = [chr(ord("A") + i) for i in range(sess["num_samples"])]
    responses = db.list_responses(session_id)

    # Per-sample attribute lookup
    products = {p["id"]: p for p in db.list_products()}
    sample_products = {}     # label -> product dict
    sample_attrs = {}        # label -> [attr, ...]
    for L in sample_labels:
        pid = db.get_sample_product_id(sess, L)
        prod = products.get(pid) if pid else None
        sample_products[L] = prod
        sample_attrs[L] = db.list_attributes(pid) if pid else []

    status_emoji = "🟢 Open" if sess["status"] == "open" else "🔒 Closed"
    st.markdown(f"### {sess['name']}")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Status", status_emoji)
    c2.metric("Samples", sess["num_samples"])
    c3.metric("Unique tasters", len({r["taster_name"] for r in responses}))
    c4.metric("Total responses", len(responses))

    with st.expander("🔑 Sample identity (admin only)", expanded=True):
        rows = []
        for L in sample_labels:
            prod = sample_products[L]
            rows.append({
                "Sample": L,
                "Product": prod["name"] if prod else "—",
                "Identity": db.get_sample_identity(sess, L) or "—",
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    if not responses:
        st.info("No responses yet. Share the link to start collecting answers.")
        return

    df = _build_dataframe(responses, sample_attrs)
    df = df.sort_values("submitted_at").drop_duplicates(["taster", "sample"], keep="last")

    present_samples = [L for L in sample_labels if L in df["sample"].unique()]

    # ── Cross-sample comparison on shared attribute names ───────────────────
    shared_attrs = _shared_attrs_across_samples(sample_attrs, present_samples)
    shared_scale = [a for a in shared_attrs if a["type"] == "scale"]

    if len(present_samples) >= 2 and shared_scale:
        st.markdown("## Cross-sample comparison")
        st.caption(
            "Attributes shared across the samples' products. "
            "If samples use different products, only matching attribute names appear here."
        )
        _render_scale_table(df, shared_scale, present_samples)
        if len(shared_scale) >= 3:
            _render_radar(df, shared_scale, present_samples)
        _render_ranking(df, shared_scale, present_samples, sess, sample_products)

    # ── Per-sample detail ───────────────────────────────────────────────────
    st.markdown("## Per-sample breakdown")
    for L in present_samples:
        prod = sample_products[L]
        prod_label = prod["name"] if prod else "—"
        identity = db.get_sample_identity(sess, L) or "—"
        sample_df = df[df["sample"] == L]
        with st.expander(
            f"Sample {L} · {prod_label} · _{identity}_ "
            f"({len(sample_df)} responses)",
            expanded=False,
        ):
            _render_sample_detail(sample_df, sample_attrs[L])

    # ── Export & raw data ───────────────────────────────────────────────────
    st.markdown("## 📥 Export")
    safe_name = "".join(c if c.isalnum() else "_" for c in sess["name"])
    csv_bytes = df.to_csv(index=False).encode("utf-8")
    xlsx_bytes = _build_excel_report(
        sess, sample_attrs, sample_products, df, present_samples, sample_labels
    )
    c1, c2 = st.columns(2)
    c1.download_button(
        "⬇️ Excel report (.xlsx)",
        xlsx_bytes,
        file_name=f"tasting_{safe_name}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        type="primary",
        use_container_width=True,
    )
    c2.download_button(
        "⬇️ Raw responses (.csv)",
        csv_bytes,
        file_name=f"tasting_{safe_name}.csv",
        mime="text/csv",
        use_container_width=True,
    )
    st.caption(
        "Excel report = multi-sheet workbook (Summary, per-sample breakdown, raw responses). "
        "CSV = raw responses only."
    )
    with st.expander("📋 Raw responses preview"):
        st.dataframe(df, use_container_width=True)


def _build_dataframe(responses, sample_attrs):
    """Build a long-ish dataframe — every column = attribute name (union across samples)."""
    # Union of all attribute names across samples, indexed by (sample, attr_id) → attr_name
    all_attr_names = []
    seen = set()
    for L, attrs in sample_attrs.items():
        for a in attrs:
            if a["name"] not in seen:
                seen.add(a["name"])
                all_attr_names.append(a["name"])

    # Per-sample attr_id → name map
    attrs_by_sample = {}
    for L, attrs in sample_attrs.items():
        attrs_by_sample[L] = {str(a["id"]): a["name"] for a in attrs}

    rows = []
    for r in responses:
        row = {
            "taster": r["taster_name"],
            "sample": r["sample_label"],
            "submitted_at": r["submitted_at"],
        }
        name_map = attrs_by_sample.get(r["sample_label"], {})
        for attr_id, val in r["answers"].items():
            name = name_map.get(str(attr_id))
            if name:
                row[name] = val
        rows.append(row)
    return pd.DataFrame(rows)


def _shared_attrs_across_samples(sample_attrs, present_samples):
    """Return attribute dicts whose name appears in every present sample's product, preserving order."""
    if not present_samples:
        return []
    name_lists = [[a["name"] for a in sample_attrs[L]] for L in present_samples]
    shared_names = set(name_lists[0])
    for names in name_lists[1:]:
        shared_names &= set(names)
    # Preserve the order from the first sample
    ordered_names = [n for n in name_lists[0] if n in shared_names]
    by_name = OrderedDict()
    for a in sample_attrs[present_samples[0]]:
        if a["name"] in shared_names and a["name"] not in by_name:
            by_name[a["name"]] = a
    return [by_name[n] for n in ordered_names if n in by_name]


def _render_scale_table(df, scale_attrs, samples) -> None:
    st.markdown("#### Numeric scores — mean ± std (n)")
    agg_rows = []
    for a in scale_attrs:
        row = {"Attribute": a["name"]}
        for s in samples:
            if a["name"] not in df.columns:
                row[f"Sample {s}"] = "—"
                continue
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
            if a["name"] not in df.columns:
                means.append(0.0)
                continue
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


def _render_ranking(df, scale_attrs, samples, sess, sample_products) -> None:
    st.markdown("#### Overall ranking")
    st.caption("Average of shared numeric attributes per sample.")
    rank_rows = []
    for s in samples:
        sub = df[df["sample"] == s]
        all_vals = []
        for a in scale_attrs:
            if a["name"] not in sub.columns:
                continue
            all_vals.extend(pd.to_numeric(sub[a["name"]], errors="coerce").dropna().tolist())
        if all_vals:
            prod = sample_products.get(s)
            rank_rows.append(
                {
                    "Sample": s,
                    "Product": prod["name"] if prod else "—",
                    "Identity": db.get_sample_identity(sess, s) or "—",
                    "Overall avg": round(sum(all_vals) / len(all_vals), 2),
                    "n scores": len(all_vals),
                }
            )
    if rank_rows:
        rank_df = pd.DataFrame(rank_rows).sort_values("Overall avg", ascending=False).reset_index(drop=True)
        rank_df.insert(0, "Rank", range(1, len(rank_df) + 1))
        st.dataframe(rank_df, use_container_width=True, hide_index=True)


def _render_sample_detail(sample_df, attrs) -> None:
    scale_attrs = [a for a in attrs if a["type"] == "scale"]
    select_attrs = [a for a in attrs if a["type"] == "select"]
    multi_attrs = [a for a in attrs if a["type"] == "multiselect"]
    text_attrs = [a for a in attrs if a["type"] == "text"]

    if scale_attrs:
        rows = []
        for a in scale_attrs:
            if a["name"] not in sample_df.columns:
                continue
            vals = pd.to_numeric(sample_df[a["name"]], errors="coerce").dropna()
            if len(vals):
                std = vals.std() if len(vals) > 1 else 0.0
                rows.append({
                    "Attribute": a["name"],
                    "Mean": f"{vals.mean():.2f}",
                    "Std": f"{std:.2f}",
                    "n": len(vals),
                })
        if rows:
            st.markdown("**Numeric**")
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    for a in select_attrs:
        if a["name"] not in sample_df.columns:
            continue
        st.markdown(f"**{a['name']}** _(single choice)_")
        counts = sample_df[a["name"]].dropna().value_counts()
        if len(counts):
            st.dataframe(counts.rename("count"), use_container_width=True)
        else:
            st.caption("_No answers._")

    for a in multi_attrs:
        if a["name"] not in sample_df.columns:
            continue
        st.markdown(f"**{a['name']}** _(multi choice)_")
        c = Counter()
        for v in sample_df[a["name"]]:
            if isinstance(v, list):
                c.update(v)
        if c:
            st.dataframe(pd.Series(dict(c.most_common())).rename("count"), use_container_width=True)
        else:
            st.caption("_No answers._")

    for a in text_attrs:
        if a["name"] not in sample_df.columns:
            continue
        st.markdown(f"**{a['name']}** _(free-text notes)_")
        sub = sample_df[["taster", a["name"]]].dropna()
        sub = sub[sub[a["name"]].astype(str).str.strip() != ""]
        if sub.empty:
            st.caption("_No notes._")
        else:
            for _, row in sub.iterrows():
                st.markdown(f"- **{row['taster']}:** {row[a['name']]}")


# ── Excel report ─────────────────────────────────────────────────────────────

def _build_excel_report(sess, sample_attrs, sample_products, df, present_samples, all_samples):
    """Return bytes of a multi-sheet .xlsx report covering everything in the Results screen."""
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        _write_summary_sheet(writer, sess, sample_attrs, sample_products, df, present_samples, all_samples)
        for L in all_samples:
            _write_sample_sheet(writer, L, sess, sample_attrs[L], sample_products.get(L), df[df["sample"] == L])
        df.to_excel(writer, sheet_name="Raw responses", index=False)
    return buf.getvalue()


def _write_block(writer, sheet, start_row, title, data):
    """Write a titled block (title row, then a DataFrame). Returns next free row."""
    title_df = pd.DataFrame([[title]])
    title_df.to_excel(writer, sheet_name=sheet, index=False, header=False, startrow=start_row)
    start_row += 1
    if data is None or (isinstance(data, pd.DataFrame) and data.empty):
        empty_df = pd.DataFrame([["(no data)"]])
        empty_df.to_excel(writer, sheet_name=sheet, index=False, header=False, startrow=start_row)
        return start_row + 2
    data.to_excel(writer, sheet_name=sheet, index=False, startrow=start_row)
    return start_row + len(data) + 2  # header row + rows + blank


def _write_summary_sheet(writer, sess, sample_attrs, sample_products, df, present_samples, all_samples):
    sheet = "Summary"
    row = 0

    facts = pd.DataFrame([
        {"Field": "Session", "Value": sess["name"]},
        {"Field": "Created", "Value": sess["created_at"]},
        {"Field": "Status", "Value": sess["status"]},
        {"Field": "Closed at", "Value": sess.get("closed_at") or "—"},
        {"Field": "Samples", "Value": sess["num_samples"]},
        {"Field": "Unique tasters", "Value": int(df["taster"].nunique()) if len(df) else 0},
        {"Field": "Total responses", "Value": int(len(df))},
    ])
    row = _write_block(writer, sheet, row, "Session facts", facts)

    ident_rows = []
    for L in all_samples:
        prod = sample_products.get(L)
        ident_rows.append({
            "Sample": L,
            "Product": prod["name"] if prod else "—",
            "Identity": db.get_sample_identity(sess, L) or "—",
            "Responses": int((df["sample"] == L).sum()) if len(df) else 0,
        })
    row = _write_block(writer, sheet, row, "Sample identities (admin only)", pd.DataFrame(ident_rows))

    shared_attrs = _shared_attrs_across_samples(sample_attrs, present_samples)
    shared_scale = [a for a in shared_attrs if a["type"] == "scale"]

    if shared_scale and present_samples:
        comp_rows = []
        for a in shared_scale:
            r = {"Attribute": a["name"]}
            for s in present_samples:
                vals = pd.to_numeric(df[df["sample"] == s].get(a["name"], pd.Series(dtype=float)), errors="coerce").dropna()
                if len(vals):
                    std = vals.std() if len(vals) > 1 else 0.0
                    r[f"Sample {s} mean"] = round(float(vals.mean()), 2)
                    r[f"Sample {s} std"] = round(float(std), 2)
                    r[f"Sample {s} n"] = int(len(vals))
                else:
                    r[f"Sample {s} mean"] = None
                    r[f"Sample {s} std"] = None
                    r[f"Sample {s} n"] = 0
            comp_rows.append(r)
        row = _write_block(writer, sheet, row, "Cross-sample numeric comparison", pd.DataFrame(comp_rows))

        rank_rows = []
        for s in present_samples:
            sub = df[df["sample"] == s]
            vals_all = []
            for a in shared_scale:
                if a["name"] in sub.columns:
                    vals_all.extend(pd.to_numeric(sub[a["name"]], errors="coerce").dropna().tolist())
            if vals_all:
                prod = sample_products.get(s)
                rank_rows.append({
                    "Sample": s,
                    "Product": prod["name"] if prod else "—",
                    "Identity": db.get_sample_identity(sess, s) or "—",
                    "Overall avg": round(sum(vals_all) / len(vals_all), 2),
                    "n scores": len(vals_all),
                })
        if rank_rows:
            rank_df = pd.DataFrame(rank_rows).sort_values("Overall avg", ascending=False).reset_index(drop=True)
            rank_df.insert(0, "Rank", range(1, len(rank_df) + 1))
            row = _write_block(writer, sheet, row, "Overall ranking", rank_df)


def _write_sample_sheet(writer, label, sess, attrs, prod, sample_df):
    sheet = f"Sample {label}"[:31]
    row = 0

    header = pd.DataFrame([
        {"Field": "Sample", "Value": label},
        {"Field": "Product", "Value": prod["name"] if prod else "—"},
        {"Field": "Identity (admin only)", "Value": db.get_sample_identity(sess, label) or "—"},
        {"Field": "Responses", "Value": int(len(sample_df))},
    ])
    row = _write_block(writer, sheet, row, f"Sample {label}", header)

    if sample_df.empty:
        return

    scale_attrs = [a for a in attrs if a["type"] == "scale"]
    num_rows = []
    for a in scale_attrs:
        if a["name"] not in sample_df.columns:
            continue
        vals = pd.to_numeric(sample_df[a["name"]], errors="coerce").dropna()
        if len(vals):
            std = vals.std() if len(vals) > 1 else 0.0
            num_rows.append({
                "Attribute": a["name"],
                "Mean": round(float(vals.mean()), 2),
                "Std": round(float(std), 2),
                "Min": float(vals.min()),
                "Max": float(vals.max()),
                "n": int(len(vals)),
            })
    if num_rows:
        row = _write_block(writer, sheet, row, "Numeric scores", pd.DataFrame(num_rows))

    for a in attrs:
        if a["type"] != "select" or a["name"] not in sample_df.columns:
            continue
        counts = sample_df[a["name"]].dropna().value_counts()
        if len(counts):
            cdf = counts.reset_index()
            cdf.columns = ["Option", "Count"]
            row = _write_block(writer, sheet, row, f"{a['name']} (single choice)", cdf)

    for a in attrs:
        if a["type"] != "multiselect" or a["name"] not in sample_df.columns:
            continue
        c = Counter()
        for v in sample_df[a["name"]]:
            if isinstance(v, list):
                c.update(v)
        if c:
            cdf = pd.DataFrame(c.most_common(), columns=["Option", "Count"])
            row = _write_block(writer, sheet, row, f"{a['name']} (multi choice)", cdf)

    for a in attrs:
        if a["type"] != "text" or a["name"] not in sample_df.columns:
            continue
        sub = sample_df[["taster", a["name"]]].dropna()
        sub = sub[sub[a["name"]].astype(str).str.strip() != ""]
        if not sub.empty:
            tdf = sub.rename(columns={"taster": "Taster", a["name"]: "Note"})
            row = _write_block(writer, sheet, row, f"{a['name']} (free-text notes)", tdf)
