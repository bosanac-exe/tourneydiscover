"""Streamlit view of the running tournament list produced by update_running_list.py."""
import json
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from filters import is_relevant, matched_rules

STORE_PATH = Path("data") / "tournaments.json"
SAFE_URL_PREFIX = "https://ota.tournamentsoftware.com/"

st.set_page_config(page_title="Tournament Discovery", page_icon="🎾", layout="wide")


@st.cache_data(ttl=300)
def load_store(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    with p.open(encoding="utf-8") as fh:
        return json.load(fh)


store = load_store(str(STORE_PATH))

st.title("🎾 Tournament Discovery")

if not store or not store.get("tournaments"):
    st.warning("No tournament data yet. Run `python update_running_list.py` first.")
    st.stop()

records = store["tournaments"]
df = pd.DataFrame(records)
df["relevant"] = [is_relevant(r) for r in records]
df["matched"] = [", ".join(matched_rules(r)) for r in records]
df["start_date"] = pd.to_datetime(df["start_date"], errors="coerce").dt.date
df["end_date"] = pd.to_datetime(df["end_date"], errors="coerce").dt.date
df["discovered_date"] = pd.to_datetime(df.get("discovered_date"), errors="coerce").dt.date
df["entry_open_date"] = pd.to_datetime(df.get("entry_open_date"), errors="coerce")

today = date.today()
new_today = int((df["discovered_date"] == today).sum())

col1, col2, col3 = st.columns(3)
col1.metric("Matching tournaments", int(df["relevant"].sum()), help=f"{len(df)} tracked in total")
col2.metric("Discovered today", new_today)
updated_at = store.get("updated_at")
col3.metric("Last updated", datetime.fromisoformat(updated_at).strftime("%Y-%m-%d %H:%M")
            if updated_at else "—")

col_a, col_b = st.columns(2)
only_new = col_a.toggle("Show only tournaments discovered today", value=False)
show_all = col_b.toggle("Show all tournaments (ignore relevance filter)", value=False)

view = df if show_all else df[df["relevant"]]
if only_new:
    view = view[view["discovered_date"] == today]
view = view.sort_values(
    ["discovered_date", "start_date", "name"], ascending=[False, True, True]
).copy()


def as_link(row: pd.Series) -> str:
    name = str(row.get("name") or "").replace("#", " ")
    url = str(row.get("url") or "")
    # Name is carried in the URL fragment (ignored by the server) so LinkColumn can
    # display it instead of the raw URL.
    return f"{url}#{name}" if url.startswith(SAFE_URL_PREFIX) else ""


view["tournament"] = view.apply(as_link, axis=1)
if "distance_km" not in view.columns:
    view["distance_km"] = pd.NA
view["distance_km"] = pd.to_numeric(view["distance_km"], errors="coerce")
view["distance"] = view.apply(
    lambda row: f"{row['maps_url']}#{row['distance_km']:.1f} km"
    if pd.notna(row["distance_km"]) and row.get("maps_url") else "",
    axis=1,
)

table = view[["tournament", "start_date", "end_date", "entry_open_date", "discovered_date",
              "distance", "matched"]]
upcoming_entry_dates = view.loc[
    view["entry_open_date"].dt.date >= today, "entry_open_date"
]
earliest_entry_open_date = upcoming_entry_dates.min()

dimmed = "color: rgba(128,128,128,0.75); background-color: rgba(128,128,128,0.12)"
highlighted = "background-color: rgba(255, 214, 10, 0.25)"

view["is_highlighted"] = (
    pd.notna(earliest_entry_open_date)
    & (view["entry_open_date"] == earliest_entry_open_date)
)


def style_tournament_row(row: pd.Series) -> list[str]:
    styles = []
    is_earliest_opening = bool(view.loc[row.name, "is_highlighted"])
    for _ in row:
        style = highlighted if is_earliest_opening else ""
        if show_all and not view.loc[row.name, "relevant"]:
            style = f"{style}; {dimmed}" if style else dimmed
        styles.append(style)
    return styles


data = table.style.apply(style_tournament_row, axis=1)

st.dataframe(
    data,
    hide_index=True,
    width="stretch",
    height=(len(view) + 1) * 35,
    column_config={
        "tournament": st.column_config.LinkColumn(
            "Tournament", width="large", display_text=r"#(.*)$"
        ),
        "start_date": st.column_config.DateColumn("Start date", format="YYYY-MM-DD"),
        "end_date": st.column_config.DateColumn("End date", format="YYYY-MM-DD"),
        "entry_open_date": st.column_config.DateColumn(
            "Entry opens", format="ddd YYYY-MM-DD",
            help="Date entries open, taken from the tournament page",
        ),
        "discovered_date": st.column_config.DateColumn("Discovery date", format="YYYY-MM-DD"),
        "distance": st.column_config.LinkColumn(
            "Distance",
            help=f"Distance from {store.get('postal_code', 'the search postal code')}",
            display_text=r"#(.*)$",
        ),
        "matched": st.column_config.TextColumn(
            "Matched filters", help="Relevance rules this tournament satisfies"
        ),
    },
)
st.caption(
    "Greyed-out rows do not match the relevance filters. Click a column header to sort."
    if show_all else "Click a column header to sort."
)

highlighted_urls = view.loc[view["is_highlighted"], "url"].dropna().tolist()
clipboard_text = "\n".join(f"{u}," for u in highlighted_urls)
copy_button_html = f"""
<button id="copy-highlighted-btn" style="
    padding: 0.4rem 0.8rem; border-radius: 0.5rem; border: 1px solid rgba(128,128,128,0.4);
    background-color: rgba(255, 214, 10, 0.25); cursor: pointer; font-size: 0.9rem;
">📋 Copy highlighted URLs ({len(highlighted_urls)})</button>
<span id="copy-highlighted-status" style="margin-left: 0.5rem; font-size: 0.85rem;"></span>
<script>
const btn = document.getElementById("copy-highlighted-btn");
const status = document.getElementById("copy-highlighted-status");
btn.addEventListener("click", async () => {{
    const text = {json.dumps(clipboard_text)};
    try {{
        await navigator.clipboard.writeText(text);
        status.textContent = "Copied!";
    }} catch (err) {{
        status.textContent = "Copy failed: " + err;
    }}
    setTimeout(() => {{ status.textContent = ""; }}, 2000);
}});
</script>
"""
components.html(copy_button_html, height=45)

window = store.get("search_window", {})
st.caption(
    f"Search window {window.get('start', '?')} → {window.get('end', '?')} "
    f"· postal code {store.get('postal_code', '?')}"
)
