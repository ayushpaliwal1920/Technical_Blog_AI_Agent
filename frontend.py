from __future__ import annotations

import json
import os
import re
import zipfile
from datetime import date
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, Optional, List, Iterator, Tuple

import streamlit as st  # type: ignore[import-not-found]

# -----------------------------
# Import your compiled LangGraph app
# -----------------------------
from backend import app


# -----------------------------
# Helpers
# -----------------------------
def safe_slug(title: str) -> str:
    s = title.strip().lower()
    s = re.sub(r"[^a-z0-9 _-]+", "", s)
    s = re.sub(r"\s+", "_", s).strip("_")
    return s or "blog"


def bundle_zip(md_text: str, md_filename: str, images_dir: Path) -> bytes:
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr(md_filename, md_text.encode("utf-8"))

        if images_dir.exists() and images_dir.is_dir():
            for p in images_dir.rglob("*"):
                if p.is_file():
                    z.write(p, arcname=str(p))
    return buf.getvalue()


def images_zip(images_dir: Path) -> Optional[bytes]:
    if not images_dir.exists() or not images_dir.is_dir():
        return None
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for p in images_dir.rglob("*"):
            if p.is_file():
                z.write(p, arcname=str(p))
    return buf.getvalue()


def try_stream(graph_app, inputs: Dict[str, Any]) -> Iterator[Tuple[str, Any]]:
    """
    Stream graph progress if available; else invoke.
    Yields ("updates"/"values"/"final", payload).
    """
    try:
        for step in graph_app.stream(inputs, stream_mode="updates"):
            yield ("updates", step)
        out = graph_app.invoke(inputs)
        yield ("final", out)
        return
    except Exception:
        pass

    try:
        for step in graph_app.stream(inputs, stream_mode="values"):
            yield ("values", step)
        out = graph_app.invoke(inputs)
        yield ("final", out)
        return
    except Exception:
        pass

    out = graph_app.invoke(inputs)
    yield ("final", out)


def extract_latest_state(current_state: Dict[str, Any], step_payload: Any) -> Dict[str, Any]:
    if isinstance(step_payload, dict):
        if len(step_payload) == 1 and isinstance(next(iter(step_payload.values())), dict):
            inner = next(iter(step_payload.values()))
            current_state.update(inner)
        else:
            current_state.update(step_payload)
    return current_state


# -----------------------------
# Markdown renderer that supports local images
# -----------------------------
_MD_IMG_RE = re.compile(r"!\[(?P<alt>[^\]]*)\]\((?P<src>[^)]+)\)")
_CAPTION_LINE_RE = re.compile(r"^\*(?P<cap>.+)\*$")


def _resolve_image_path(src: str) -> Path:
    src = src.strip().lstrip("./")
    return Path(src).resolve()


def render_markdown_with_local_images(md: str):
    matches = list(_MD_IMG_RE.finditer(md))
    if not matches:
        st.markdown(md, unsafe_allow_html=False)
        return

    parts: List[Tuple[str, str]] = []
    last = 0
    for m in matches:
        before = md[last : m.start()]
        if before:
            parts.append(("md", before))

        alt = (m.group("alt") or "").strip()
        src = (m.group("src") or "").strip()
        parts.append(("img", f"{alt}|||{src}"))
        last = m.end()

    tail = md[last:]
    if tail:
        parts.append(("md", tail))

    i = 0
    while i < len(parts):
        kind, payload = parts[i]

        if kind == "md":
            st.markdown(payload, unsafe_allow_html=False)
            i += 1
            continue

        alt, src = payload.split("|||", 1)

        caption = None
        if i + 1 < len(parts) and parts[i + 1][0] == "md":
            nxt = parts[i + 1][1].lstrip()
            if nxt.strip():
                first_line = nxt.splitlines()[0].strip()
                mcap = _CAPTION_LINE_RE.match(first_line)
                if mcap:
                    caption = mcap.group("cap").strip()
                    rest = "\n".join(nxt.splitlines()[1:])
                    parts[i + 1] = ("md", rest)

        if src.startswith("http://") or src.startswith("https://"):
            st.image(src, caption=caption or (alt or None), use_container_width=True)
        else:
            img_path = _resolve_image_path(src)
            if img_path.exists():
                st.image(str(img_path), caption=caption or (alt or None), use_container_width=True)
            else:
                st.warning(f"Image not found: `{src}` (looked for `{img_path}`)")

        i += 1


# -----------------------------
# ✅ NEW: Past blogs helpers
# -----------------------------
def list_past_blogs() -> List[Path]:
    """
    Returns .md files in current working directory, newest first.
    Filters out obvious non-blog markdown files if needed.
    """
    cwd = Path(".")
    files = [p for p in cwd.glob("*.md") if p.is_file()]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files


def read_md_file(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace")


def extract_title_from_md(md: str, fallback: str) -> str:
    """
    Use first '# ' heading as title if present.
    """
    for line in md.splitlines():
        if line.startswith("# "):
            t = line[2:].strip()
            return t or fallback
    return fallback



# -----------------------------
# Premium Streamlit UI
# -----------------------------
st.set_page_config(
    page_title="BlogForge AI",
    page_icon="✦",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------- Theme ----------
st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Space+Grotesk:wght@500;600;700&display=swap');

    :root {
        --bg: #070a12;
        --panel: #0e1320;
        --panel-2: #111827;
        --border: rgba(255,255,255,.09);
        --muted: #8d98ad;
        --text: #f5f7fb;
        --accent: #7c5cff;
        --accent-2: #22d3ee;
        --success: #34d399;
        --warning: #fbbf24;
    }

    .stApp {
        background:
            radial-gradient(circle at 15% 0%, rgba(124,92,255,.13), transparent 28%),
            radial-gradient(circle at 88% 10%, rgba(34,211,238,.08), transparent 25%),
            var(--bg);
        color: var(--text);
        font-family: 'DM Sans', sans-serif;
    }

    [data-testid="stHeader"] {
        background: rgba(7,10,18,.72);
        backdrop-filter: blur(14px);
    }

    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #0a0e18 0%, #080b13 100%);
        border-right: 1px solid var(--border);
    }

    [data-testid="stSidebar"] > div:first-child {
        padding-top: 1.25rem;
    }

    h1, h2, h3, h4 {
        font-family: 'Space Grotesk', sans-serif !important;
        letter-spacing: -.025em;
    }

    .hero {
        padding: 28px 30px;
        border: 1px solid var(--border);
        border-radius: 24px;
        background:
            linear-gradient(135deg, rgba(124,92,255,.16), rgba(17,24,39,.7) 48%, rgba(34,211,238,.06));
        box-shadow: 0 20px 70px rgba(0,0,0,.24);
        margin-bottom: 22px;
    }

    .hero-kicker {
        color: #a99cff;
        font-size: .78rem;
        font-weight: 700;
        letter-spacing: .13em;
        text-transform: uppercase;
        margin-bottom: 8px;
    }

    .hero-title {
        font-family: 'Space Grotesk', sans-serif;
        font-size: clamp(2rem, 4vw, 3.25rem);
        line-height: 1.02;
        font-weight: 700;
        margin: 0;
        color: #fff;
    }

    .hero-subtitle {
        color: #aab3c4;
        max-width: 760px;
        margin-top: 12px;
        font-size: 1rem;
        line-height: 1.65;
    }

    .section-title {
        display: flex;
        align-items: center;
        gap: 10px;
        margin: 4px 0 14px;
        font-family: 'Space Grotesk', sans-serif;
        font-size: 1.18rem;
        font-weight: 700;
    }

    .metric-card {
        border: 1px solid var(--border);
        border-radius: 16px;
        padding: 16px 18px;
        background: rgba(14,19,32,.82);
        min-height: 94px;
    }

    .metric-label {
        color: var(--muted);
        font-size: .78rem;
        text-transform: uppercase;
        letter-spacing: .07em;
        font-weight: 600;
    }

    .metric-value {
        color: #fff;
        font-family: 'Space Grotesk', sans-serif;
        font-size: 1.65rem;
        font-weight: 700;
        margin-top: 4px;
    }

    .metric-hint {
        color: #68748b;
        font-size: .76rem;
        margin-top: 2px;
    }

    .source-card {
        border: 1px solid var(--border);
        border-radius: 14px;
        padding: 14px 16px;
        margin-bottom: 10px;
        background: rgba(14,19,32,.72);
    }

    .source-title {
        color: #f5f7fb;
        font-weight: 650;
        font-size: .95rem;
        margin-bottom: 5px;
    }

    .source-meta {
        color: #7e899e;
        font-size: .78rem;
    }

    .source-link {
        color: #9d8dff !important;
        text-decoration: none;
        font-size: .8rem;
    }

    .status-pill {
        display: inline-block;
        padding: 5px 10px;
        border-radius: 999px;
        font-size: .72rem;
        font-weight: 700;
        letter-spacing: .03em;
        background: rgba(52,211,153,.11);
        color: #6ee7b7;
        border: 1px solid rgba(52,211,153,.2);
    }

    .empty-state {
        text-align: center;
        padding: 58px 20px;
        border: 1px dashed rgba(255,255,255,.12);
        border-radius: 20px;
        background: rgba(14,19,32,.45);
    }

    .empty-icon {
        font-size: 2.3rem;
        margin-bottom: 8px;
    }

    .empty-title {
        font-family: 'Space Grotesk', sans-serif;
        font-size: 1.15rem;
        font-weight: 700;
    }

    .empty-copy {
        color: #7e899e;
        margin-top: 6px;
    }

    .stButton > button {
        border-radius: 11px;
        border: 1px solid var(--border);
        font-weight: 650;
        min-height: 42px;
    }

    .stButton > button[kind="primary"] {
        background: linear-gradient(135deg, #7c5cff, #6351d8);
        border: 0;
        box-shadow: 0 10px 30px rgba(124,92,255,.25);
    }

    .stDownloadButton > button {
        border-radius: 10px;
        font-weight: 600;
    }

    div[data-baseweb="tab-list"] {
        gap: 5px;
        border-bottom: 1px solid var(--border);
    }

    button[data-baseweb="tab"] {
        color: #8994a8;
        padding: 12px 15px;
    }

    button[data-baseweb="tab"][aria-selected="true"] {
        color: #fff;
    }

    .sidebar-brand {
        padding: 0 4px 18px;
    }

    .brand-mark {
        display: inline-flex;
        width: 34px;
        height: 34px;
        align-items: center;
        justify-content: center;
        border-radius: 10px;
        background: linear-gradient(135deg, #7c5cff, #22d3ee);
        color: white;
        font-weight: 800;
        margin-right: 9px;
    }

    .brand-name {
        font-family: 'Space Grotesk', sans-serif;
        font-size: 1.18rem;
        font-weight: 700;
        vertical-align: middle;
    }

    .sidebar-label {
        color: #8994a8;
        font-size: .74rem;
        text-transform: uppercase;
        letter-spacing: .08em;
        font-weight: 700;
        margin: 8px 0 7px;
    }

    .footer-note {
        color: #68748b;
        font-size: .72rem;
        text-align: center;
        margin-top: 22px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------- State ----------
if "last_out" not in st.session_state:
    st.session_state["last_out"] = None
if "logs" not in st.session_state:
    st.session_state["logs"] = []
if "running" not in st.session_state:
    st.session_state["running"] = False

def as_dict(value):
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if isinstance(value, dict):
        return value
    try:
        return json.loads(json.dumps(value, default=str))
    except Exception:
        return {}

def get_plan(out):
    return as_dict(out.get("plan")) if out else {}

def get_blog_title(out):
    final_md = (out or {}).get("final") or ""
    plan = get_plan(out)
    return plan.get("blog_title") or extract_title_from_md(final_md, "Untitled blog")

def add_log(message: str):
    st.session_state["logs"].append(message)
    st.session_state["logs"] = st.session_state["logs"][-150:]

# ---------- Sidebar ----------
with st.sidebar:
    st.markdown(
        """
        <div class="sidebar-brand">
            <span class="brand-mark">✦</span>
            <span class="brand-name">BlogForge AI</span>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown('<div class="sidebar-label">Create</div>', unsafe_allow_html=True)
    topic = st.text_area(
        "What should I write about?",
        height=135,
        placeholder="e.g. How AI agents are changing software engineering in 2026",
        label_visibility="collapsed",
    )
    as_of = st.date_input("Research date", value=date.today())
    run_btn = st.button("✦  Generate Blog", type="primary", use_container_width=True)

    st.divider()
    st.markdown('<div class="sidebar-label">Library</div>', unsafe_allow_html=True)

    past_files = list_past_blogs()
    selected_md_file = None

    if not past_files:
        st.caption("No saved Markdown blogs found in the current folder.")
    else:
        labels = []
        mapping = {}
        for p in past_files[:50]:
            try:
                md_text = read_md_file(p)
                title = extract_title_from_md(md_text, p.stem)
            except Exception:
                title = p.stem
            label = f"{title}  ·  {p.name}"
            labels.append(label)
            mapping[label] = p

        selected_label = st.selectbox(
            "Saved blogs",
            labels,
            label_visibility="collapsed",
        )
        selected_md_file = mapping.get(selected_label)

        if st.button("Open selected blog", use_container_width=True):
            if selected_md_file:
                md_text = read_md_file(selected_md_file)
                st.session_state["last_out"] = {
                    "plan": None,
                    "evidence": [],
                    "image_specs": [],
                    "final": md_text,
                }
                add_log(f"Loaded: {selected_md_file.name}")
                st.rerun()

    st.markdown(
        '<div class="footer-note">LangGraph-powered writing workspace</div>',
        unsafe_allow_html=True,
    )

# ---------- Hero ----------
st.markdown(
    """
    <div class="hero">
        <div class="hero-kicker">AI writing workspace</div>
        <div class="hero-title">Research. Plan. Write.<br>Publish with confidence.</div>
        <div class="hero-subtitle">
            Turn a simple topic into a structured, research-backed blog with
            evidence, images, Markdown output, and transparent generation progress.
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# ---------- Generation ----------
if run_btn:
    if not topic.strip():
        st.warning("Enter a topic first.")
        st.stop()

    inputs: Dict[str, Any] = {
        "topic": topic.strip(),
        "mode": "",
        "needs_research": False,
        "queries": [],
        "evidence": [],
        "plan": None,
        "as_of": as_of.isoformat(),
        "recency_days": 7,
        "sections": [],
        "merged_md": "",
        "md_with_placeholders": "",
        "image_specs": [],
        "final": "",
    }

    st.session_state["running"] = True
    add_log(f"Generation started: {topic.strip()}")

    status = st.status("Building your blog…", expanded=True)
    progress_area = st.empty()
    current_state: Dict[str, Any] = {}
    last_node = None
    completed = False

    try:
        for kind, payload in try_stream(app, inputs):
            if kind in ("updates", "values"):
                node_name = None
                if (
                    isinstance(payload, dict)
                    and len(payload) == 1
                    and isinstance(next(iter(payload.values())), dict)
                ):
                    node_name = next(iter(payload.keys()))

                if node_name and node_name != last_node:
                    status.write(f"**Step:** `{node_name}`")
                    add_log(f"Node completed: {node_name}")
                    last_node = node_name

                current_state = extract_latest_state(current_state, payload)

                plan = current_state.get("plan")
                plan_dict = as_dict(plan) if plan else {}
                summary = {
                    "Mode": current_state.get("mode") or "—",
                    "Research": "Yes" if current_state.get("needs_research") else "No",
                    "Sources": len(current_state.get("evidence") or []),
                    "Tasks": len(plan_dict.get("tasks") or []),
                    "Sections": len(current_state.get("sections") or []),
                    "Images": len(current_state.get("image_specs") or []),
                }
                progress_area.json(summary)

            elif kind == "final":
                st.session_state["last_out"] = payload
                completed = True
                status.update(
                    label="Blog generated successfully",
                    state="complete",
                    expanded=False,
                )
                add_log("Final state received.")
    except Exception as exc:
        add_log(f"Generation error: {type(exc).__name__}: {exc}")
        status.update(label="Generation failed", state="error")
        st.error(f"Generation failed: {exc}")

    st.session_state["running"] = False

# ---------- Workspace ----------
out = st.session_state.get("last_out")

if not out:
    st.markdown(
        """
        <div class="empty-state">
            <div class="empty-icon">✦</div>
            <div class="empty-title">Your writing workspace is ready</div>
            <div class="empty-copy">
                Add a topic from the sidebar to generate your first research-backed blog.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.stop()

plan = get_plan(out)
evidence = out.get("evidence") or []
final_md = out.get("final") or ""
specs = out.get("image_specs") or []
images_dir = Path("images")

# ---------- Overview ----------
title = get_blog_title(out)
task_count = len(plan.get("tasks") or [])
image_count = len(specs)
source_count = len(evidence)
section_count = len(out.get("sections") or [])

st.markdown('<div class="section-title">✦ Overview</div>', unsafe_allow_html=True)

m1, m2, m3, m4, m5 = st.columns(5)
metrics = [
    (m1, "Blog title", title, "Generated"),
    (m2, "Sources", source_count, "Evidence items"),
    (m3, "Tasks", task_count, "Writing plan"),
    (m4, "Sections", section_count, "Completed"),
    (m5, "Images", image_count, "Planned"),
]
for col, label, value, hint in metrics:
    with col:
        st.markdown(
            f"""
            <div class="metric-card">
                <div class="metric-label">{label}</div>
                <div class="metric-value">{value}</div>
                <div class="metric-hint">{hint}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

st.write("")

# ---------- Tabs ----------
tab_preview, tab_plan, tab_sources, tab_images, tab_logs = st.tabs(
    ["📝  Article", "🧩  Plan", "🔎  Sources", "🖼️  Media", "🧾  Activity"]
)

# ---------- Article ----------
with tab_preview:
    left, right = st.columns([1, 1], gap="large")

    with left:
        st.markdown('<div class="section-title">Article preview</div>', unsafe_allow_html=True)
        if final_md:
            render_markdown_with_local_images(final_md)
        else:
            st.info("The graph returned no final Markdown.")

    with right:
        st.markdown('<div class="section-title">Export</div>', unsafe_allow_html=True)

        md_filename = f"{safe_slug(title)}.md"
        st.download_button(
            "⬇️  Download Markdown",
            data=final_md.encode("utf-8"),
            file_name=md_filename,
            mime="text/markdown",
            use_container_width=True,
        )

        bundle = bundle_zip(final_md, md_filename, images_dir)
        st.download_button(
            "📦  Download complete bundle",
            data=bundle,
            file_name=f"{safe_slug(title)}_bundle.zip",
            mime="application/zip",
            use_container_width=True,
        )

        st.divider()
        st.markdown('<div class="section-title">Article details</div>', unsafe_allow_html=True)
        st.write(f"**Title:** {title}")
        st.write(f"**Audience:** {plan.get('audience', '—')}")
        st.write(f"**Tone:** {plan.get('tone', '—')}")
        st.write(f"**Blog type:** {plan.get('blog_kind', '—')}")

        if final_md:
            st.caption(f"{len(final_md):,} characters · {len(final_md.split()):,} words")

# ---------- Plan ----------
with tab_plan:
    st.markdown('<div class="section-title">🧩 Content strategy</div>', unsafe_allow_html=True)

    if not plan:
        st.info("No structured plan was returned.")
    else:
        a, b, c = st.columns(3)
        with a:
            st.markdown("**Audience**")
            st.write(plan.get("audience", "—"))
        with b:
            st.markdown("**Tone**")
            st.write(plan.get("tone", "—"))
        with c:
            st.markdown("**Blog type**")
            st.write(plan.get("blog_kind", "—"))

        tasks = plan.get("tasks") or []
        if tasks:
            st.write("")
            rows = []
            for task in tasks:
                rows.append(
                    {
                        "ID": task.get("id"),
                        "Section": task.get("title"),
                        "Words": task.get("target_words"),
                        "Research": "Yes" if task.get("requires_research") else "No",
                        "Citations": "Yes" if task.get("requires_citations") else "No",
                        "Code": "Yes" if task.get("requires_code") else "No",
                    }
                )
            st.dataframe(
                sorted(rows, key=lambda row: (row["ID"] is None, row["ID"])),
                use_container_width=True,
                hide_index=True,
            )

            with st.expander("View raw task details"):
                st.json(tasks)

# ---------- Sources ----------
with tab_sources:
    st.markdown('<div class="section-title">🔎 Research evidence</div>', unsafe_allow_html=True)

    if not evidence:
        st.info("No evidence was returned. The run may have used closed-book mode or returned no research results.")
    else:
        for item in evidence:
            e = as_dict(item)
            source_title = e.get("title") or "Untitled source"
            source_url = e.get("url") or ""
            published = e.get("published_at") or "Publication date unavailable"
            source_name = e.get("source") or "Unknown source"

            link_html = (
                f'<a class="source-link" href="{source_url}" target="_blank">Open source ↗</a>'
                if source_url
                else ""
            )

            st.markdown(
                f"""
                <div class="source-card">
                    <div class="source-title">{source_title}</div>
                    <div class="source-meta">{source_name} · {published}</div>
                    <div style="margin-top:7px">{link_html}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

# ---------- Images ----------
with tab_images:
    st.markdown('<div class="section-title">🖼️ Visual assets</div>', unsafe_allow_html=True)

    if specs:
        with st.expander("View image generation plan"):
            st.json(specs)

    if images_dir.exists():
        image_files = sorted([p for p in images_dir.iterdir() if p.is_file()])
    else:
        image_files = []

    if not image_files:
        if specs:
            st.info("Image specifications exist, but no local image files were found yet.")
        else:
            st.info("No images were generated for this blog.")
    else:
        cols = st.columns(3)
        for index, image_path in enumerate(image_files):
            with cols[index % 3]:
                st.image(str(image_path), caption=image_path.name, use_container_width=True)

        image_zip = images_zip(images_dir)
        if image_zip:
            st.download_button(
                "⬇️  Download all images",
                data=image_zip,
                file_name="images.zip",
                mime="application/zip",
            )

# ---------- Logs ----------
with tab_logs:
    st.markdown('<div class="section-title">🧾 Generation activity</div>', unsafe_allow_html=True)

    if st.session_state["logs"]:
        st.text_area(
            "Event log",
            value="\n\n".join(st.session_state["logs"][-100:]),
            height=520,
            label_visibility="collapsed",
        )
    else:
        st.caption("No activity recorded yet.")

    if st.button("Clear activity log"):
        st.session_state["logs"] = []
        st.rerun()
