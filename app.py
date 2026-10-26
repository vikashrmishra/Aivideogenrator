import os
import streamlit as st

# 1. Safe dotenv import (Prevents ModuleNotFoundError on Streamlit Cloud)
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

from zero_key_agent import (
    get_video_keywords_from_prompt,
    download_real_videos,
    assemble_video
)

# 2. Fetch PIXABAY_KEY (Prioritizes Streamlit Cloud Secrets, falls back to .env)
PIXABAY_KEY = None
try:
    if "PIXABAY_KEY" in st.secrets:
        PIXABAY_KEY = st.secrets["PIXABAY_KEY"]
except Exception:
    pass

if not PIXABAY_KEY:
    PIXABAY_KEY = os.getenv("PIXABAY_KEY")

# --- Page Setup ---
st.set_page_config(
    page_title="Reelkatha by Vikash",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# --- Vikash monogram: a "V" that ends in a red record dot ---
LOGO_SVG = """<svg width="46" height="46" viewBox="0 0 48 48" xmlns="http://www.w3.org/2000/svg" aria-label="Vikash logo">
<defs><linearGradient id="vk" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#FFC46B"/><stop offset="1" stop-color="#FF8A3D"/></linearGradient></defs>
<rect width="48" height="48" rx="13" fill="url(#vk)"/>
<path d="M11 13 L23 35 L32 19" fill="none" stroke="#14110F" stroke-width="5.5" stroke-linecap="round" stroke-linejoin="round"/>
<circle cx="37" cy="12" r="4" fill="#14110F"/>
<circle cx="37" cy="12" r="1.8" fill="#FF5A4E"/>
</svg>"""

# --- Styling: warm film-stock palette, calm and simple ---
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:wght@500;700;800&family=DM+Sans:wght@400;500;600&display=swap');

    :root {
        --ink: #14110F;
        --panel: #1D1916;
        --line: #332C27;
        --text: #F3EDE6;
        --muted: #A39A90;
        --amber: #FFB547;
        --amber-deep: #FF8A3D;
        --ok: #7BD88F;
    }

    html, body, .stApp, [class*="css"] { font-family: 'DM Sans', sans-serif; }
    .stApp { background: var(--ink); color: var(--text); }
    #MainMenu, footer, header { visibility: hidden; }
    .block-container { max-width: 1180px; padding-top: 2rem; }

    /* Header */
    .brand {
        display: flex; align-items: center; justify-content: space-between;
        padding-bottom: 1.4rem; margin-bottom: 1.6rem;
        border-bottom: 1px solid var(--line);
    }
    .brand-left { display: flex; align-items: center; gap: 14px; }
    .brand-name {
        font-family: 'Bricolage Grotesque', sans-serif;
        font-size: 1.6rem; font-weight: 800; margin: 0; line-height: 1.1;
        color: var(--text);
    }
    .brand-sub { margin: 2px 0 0; font-size: 0.85rem; color: var(--muted); }
    .ready {
        display: inline-flex; align-items: center; gap: 8px;
        font-size: 0.85rem; color: var(--ok); font-weight: 500;
    }
    .ready i {
        width: 8px; height: 8px; border-radius: 50%;
        background: var(--ok); display: inline-block;
    }

    /* Panels (st.container(border=True)) */
    [data-testid="stVerticalBlockBorderWrapper"] {
        background: var(--panel);
        border: 1px solid var(--line) !important;
        border-radius: 16px !important;
    }

    h3 {
        font-family: 'Bricolage Grotesque', sans-serif !important;
        font-weight: 700 !important; letter-spacing: -0.01em;
    }

    /* Inputs */
    .stTextArea textarea, [data-baseweb="select"] > div {
        background: var(--ink) !important;
        border: 1px solid var(--line) !important;
        border-radius: 10px !important;
        color: var(--text) !important;
    }
    .stTextArea textarea:focus {
        border-color: var(--amber) !important;
        box-shadow: 0 0 0 3px rgba(255, 181, 71, 0.18) !important;
    }

    /* Sliders & radio pick up the amber accent */
    [data-testid="stSlider"] [role="slider"] { background: var(--amber) !important; }

    /* Secondary buttons = quick-idea chips */
    button[kind="secondary"], [data-testid="stBaseButton-secondary"] {
        background: transparent !important;
        color: var(--text) !important;
        border: 1px solid var(--line) !important;
        border-radius: 999px !important;
        font-size: 0.85rem !important;
        padding: 0.35rem 0.9rem !important;
        transition: border-color .15s, color .15s;
    }
    button[kind="secondary"]:hover, [data-testid="stBaseButton-secondary"]:hover {
        border-color: var(--amber) !important;
        color: var(--amber) !important;
    }

    /* Primary button = render */
    button[kind="primary"], [data-testid="stBaseButton-primary"] {
        background: linear-gradient(135deg, var(--amber), var(--amber-deep)) !important;
        color: var(--ink) !important;
        font-weight: 700 !important;
        font-size: 1.02rem !important;
        border: none !important;
        border-radius: 12px !important;
        padding: 0.8rem 1.5rem !important;
    }
    button[kind="primary"]:hover, [data-testid="stBaseButton-primary"]:hover {
        filter: brightness(1.08);
    }
    button:focus-visible { outline: 2px solid var(--amber) !important; outline-offset: 2px; }

    /* Storyboard + specs */
    .scene-badge {
        display: inline-block;
        border: 1px solid var(--line);
        color: var(--text);
        padding: 4px 12px; border-radius: 999px;
        font-size: 0.82rem; margin: 3px 3px 3px 0;
    }
    .spec-item {
        border: 1px solid var(--line); border-radius: 12px;
        padding: 10px; text-align: center;
    }
    .spec-val {
        font-family: 'Bricolage Grotesque', sans-serif;
        font-size: 1.25rem; font-weight: 700; color: var(--amber);
    }
    .spec-lbl { font-size: 0.78rem; color: var(--muted); }

    .idle {
        border: 1px dashed var(--line); border-radius: 14px;
        padding: 3rem 1.5rem; text-align: center; color: var(--muted);
    }
    .idle b { color: var(--text); }
    .hint { font-size: 0.85rem; color: var(--muted); margin: 0 0 6px; }
</style>
""", unsafe_allow_html=True)

# --- Header ---
st.markdown(f"""
<div class="brand">
    <div class="brand-left">
        {LOGO_SVG}
        <div>
            <h1 class="brand-name">Reelkatha</h1>
            <p class="brand-sub">by Vikash &middot; Turn a story into a video with real stock footage</p>
        </div>
    </div>
    <div class="ready"><i></i>{"Ready" if PIXABAY_KEY else "Key missing"}</div>
</div>
""", unsafe_allow_html=True)

# API Key Validation
if not PIXABAY_KEY:
    st.error("PIXABAY_KEY not found. Add it to your `.env` file locally or in Streamlit Cloud Secrets (Settings -> Secrets).")
    st.stop()

# --- Prompt state ---
DEFAULT_PROMPT = (
    "Cinematic exploration of artificial intelligence: glowing quantum processors, "
    "neural networks visualized in 3D, autonomous robotics, futuristic human-AI "
    "collaboration in high-tech laboratories."
)
if "prompt" not in st.session_state:
    st.session_state.prompt = DEFAULT_PROMPT

def set_prompt(text: str):
    st.session_state.prompt = text

PRESETS = {
    "Deep Space": "Futuristic spacecraft navigating an asteroid field, entering warp speed, glowing alien nebula, docking at massive orbital station.",
    "Tokyo Night": "Rain-soaked Tokyo streets at night, neon holograms, flying drone taxis, reflections on wet asphalt, cyberpunk hacker walking.",
    "Ocean Depths": "Submarine exploring bioluminescent creatures in Mariana Trench, underwater thermal vents, ancient mysterious ship ruins on sea bed.",
}

# --- Layout ---
col_studio, col_monitor = st.columns([1.1, 0.9], gap="large")

with col_studio:
    with st.container(border=True):
        st.markdown("### Your story")

        st.markdown("<p class='hint'>Need an idea? Start with one of these:</p>", unsafe_allow_html=True)
        chip_cols = st.columns(len(PRESETS))
        for col, (label, text) in zip(chip_cols, PRESETS.items()):
            with col:
                st.button(label, on_click=set_prompt, args=(text,), use_container_width=True)

        user_prompt = st.text_area(
            label="Video prompt",
            key="prompt",
            height=140,
            label_visibility="collapsed",
            placeholder="Describe the scenes, mood and camera movement you want to see..."
        )

        s_col1, s_col2 = st.columns(2)
        with s_col1:
            style_preset = st.selectbox(
                "Visual style",
                options=["Cinematic 4K Dramatic", "Drone Aerial & Landscapes", "Cyberpunk / Sci-Fi Glow", "Documentary Nature", "Fast-Paced Urban Street"]
            )
        with s_col2:
            ratio_preset = st.selectbox(
                "Format",
                options=["9:16 Vertical (Reels / Shorts)", "16:9 Landscape (YouTube / Desktop)"]
            )

        t_col1, t_col2 = st.columns(2)
        with t_col1:
            total_duration = st.slider("Video length", min_value=15, max_value=90, value=60, step=5, format="%d sec")
        with t_col2:
            scenes_count = st.slider("Number of scenes", min_value=4, max_value=20, value=14, step=2)

        pace_per_clip = total_duration / scenes_count
        st.markdown(f"<p class='hint'>About <b>{pace_per_clip:.1f}s</b> per scene</p>", unsafe_allow_html=True)

        selected_ratio = "9:16" if "9:16" in ratio_preset else "16:9"
        generate_btn = st.button("Render video", type="primary", use_container_width=True)

with col_monitor:
    with st.container(border=True):
        st.markdown("### Preview")
        preview_placeholder = st.empty()
        preview_placeholder.markdown("""
            <div class="idle">
                <p style="font-size:2.2rem; margin:0;">🎬</p>
                <p style="margin:0.5rem 0 0.2rem;"><b>Nothing rendered yet</b></p>
                <p style="font-size:0.85rem; margin:0;">Write your story, then press <b>Render video</b>.</p>
            </div>
        """, unsafe_allow_html=True)
        storyboard_placeholder = st.empty()

# --- Generation Execution ---
if generate_btn:
    output_filename = "reelkatha_render.mp4"

    with col_monitor:
        status_box = st.status("Rendering your video...", expanded=True)

        try:
            # 1. Scene planning
            status_box.write("**Step 1 of 3:** Breaking the story into scenes...")
            keywords = get_video_keywords_from_prompt(user_prompt, style=style_preset, count=scenes_count)

            status_box.write(f"Planned {len(keywords)} scenes.")
            with storyboard_placeholder.container():
                st.markdown("##### Scene list")
                badges = "".join([f'<span class="scene-badge">{kw}</span>' for kw in keywords])
                st.markdown(badges, unsafe_allow_html=True)

            # 2. Footage download (Safely handles aspect_ratio param)
            status_box.write("**Step 2 of 3:** Downloading footage from Pixabay...")
            try:
                clips = download_real_videos(keywords, aspect_ratio=selected_ratio)
            except TypeError:
                clips = download_real_videos(keywords)

            if not clips:
                status_box.update(label="No clips found. Try a different prompt.", state="error")
                st.stop()
            status_box.write(f"Downloaded {len(clips)} clips.")

            # 3. Assemble
            status_box.write(f"**Step 3 of 3:** Cropping to {selected_ratio} and compiling MP4...")
            success = assemble_video(clips, total_duration, output_filename, aspect_ratio=selected_ratio)

            if success:
                status_box.update(label="Your video is ready", state="complete", expanded=False)

                with preview_placeholder.container():
                    st.video(output_filename)

                    s1, s2, s3 = st.columns(3)
                    with s1:
                        st.markdown(f'<div class="spec-item"><div class="spec-val">{total_duration}s</div><div class="spec-lbl">Length</div></div>', unsafe_allow_html=True)
                    with s2:
                        st.markdown(f'<div class="spec-item"><div class="spec-val">{selected_ratio}</div><div class="spec-lbl">Format</div></div>', unsafe_allow_html=True)
                    with s3:
                        st.markdown(f'<div class="spec-item"><div class="spec-val">{len(clips)}</div><div class="spec-lbl">Scenes</div></div>', unsafe_allow_html=True)

                    st.write("")
                    with open(output_filename, "rb") as f:
                        st.download_button(
                            label="Download MP4",
                            data=f,
                            file_name="reelkatha_video.mp4",
                            mime="video/mp4",
                            use_container_width=True
                        )
            else:
                status_box.update(label="Could not assemble the clips.", state="error")

        except Exception as e:
            status_box.update(label="Something went wrong", state="error")
            st.error(f"Details: {e}")
