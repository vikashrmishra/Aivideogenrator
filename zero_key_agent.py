"""
zero_key_agent.py (v2 - Cloud & Local Hybrid)

Backend for the video studio app:
  1. get_video_keywords_from_prompt()  - story -> list of stock-footage search queries
  2. download_real_videos()            - smart Pixabay search + cached, parallel downloads
  3. assemble_video()                  - crop/fit, crossfade, fades, optional music -> MP4

Supports both Streamlit Cloud Secrets (st.secrets) and local .env files.
"""

import os
import re
import json
import math
import random
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, List, Optional, Tuple

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# --- 1. SAFE CONFIGURATION & SECRET MANAGEMENT ---
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Helper to read from Streamlit Secrets first, then OS environment variables
def _get_secret(key: str, default: Optional[str] = None) -> Optional[str]:
    try:
        import streamlit as st
        if key in st.secrets:
            return str(st.secrets[key])
    except Exception:
        pass
    return os.getenv(key, default)


def _pixabay_key() -> Optional[str]:
    return _get_secret("PIXABAY_KEY")


ProgressCb = Optional[Callable[[float, str], None]]  # (0.0 - 1.0, message)


def _make_session() -> requests.Session:
    """HTTP session that automatically retries on rate limits and server errors."""
    retry = Retry(
        total=3,
        backoff_factor=1.0,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
    )
    s = requests.Session()
    adapter = HTTPAdapter(max_retries=retry, pool_maxsize=8)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    return s


SESSION = _make_session()


def _report(cb: ProgressCb, fraction: float, message: str) -> None:
    if cb:
        try:
            cb(max(0.0, min(1.0, fraction)), message)
        except Exception:
            pass


# =====================================================================
# 2. PROMPT -> VISUAL KEYWORDS
# =====================================================================
_STOPWORDS = {
    "with", "that", "this", "from", "into", "over", "under", "through", "their",
    "there", "where", "while", "about", "after", "before", "between", "and", "the",
    "for", "are", "was", "were", "has", "have", "its", "his", "her", "them",
}


def _clean_keyword(kw) -> str:
    """Normalize one search query: plain lowercase text, max 3 words."""
    if isinstance(kw, dict):
        kw = next((v for v in kw.values() if isinstance(v, str)), "")
    kw = re.sub(r"[^a-zA-Z0-9\s\-]", " ", str(kw)).lower()
    return " ".join(kw.split()[:3])


def _parse_keyword_list(text: str) -> List[str]:
    """Extract a clean list of search queries from messy LLM responses."""
    start, end = text.find("["), text.rfind("]") + 1
    if start != -1 and end > start:
        try:
            data = json.loads(text[start:end])
            if isinstance(data, list):
                return [k for k in (_clean_keyword(x) for x in data) if k]
        except json.JSONDecodeError:
            pass
    lines = [re.sub(r"^[\s\-\*\d\.\)]+", "", ln) for ln in text.splitlines()]
    return [k for k in (_clean_keyword(ln) for ln in lines) if k]


_ABSTRACT = {
    "cinematic", "exploration", "visualized", "futuristic", "autonomous", "collaboration",
    "concept", "idea", "style", "mood", "feeling", "beautiful", "amazing", "epic",
}

_STYLE_EXTRAS = {
    "drone": ["aerial landscape", "mountain drone", "ocean coast aerial", "forest aerial", "city aerial", "sunset clouds"],
    "cyberpunk": ["neon city night", "rain street neon", "futuristic city", "digital code", "robot technology", "hologram light"],
    "nature": ["forest nature", "wildlife animals", "river water", "mountain peak", "birds flying", "waterfall"],
    "urban": ["city traffic", "street crowd", "subway train", "skyscraper", "night city", "people walking"],
    "cinematic": ["dramatic sky", "storm clouds", "sunset silhouette", "city night", "ocean waves", "mountain fog"],
}


def _fallback_keywords(prompt: str, style: str, count: int) -> List[str]:
    """No-LLM fallback: parses prompt phrases and mixes in style anchors."""
    out: List[str] = []
    for p in re.split(r"[,.;:\n]", prompt):
        words = [w for w in re.findall(r"[a-zA-Z]+", p.lower())
                 if len(w) > 3 and w not in _STOPWORDS and w not in _ABSTRACT]
        if words:
            phrase = " ".join(words[:3])
            if phrase not in out:
                out.append(phrase)

    extras: List[str] = []
    s = style.lower()
    for key, vals in _STYLE_EXTRAS.items():
        if key in s:
            extras = vals
            break
    extras = extras or _STYLE_EXTRAS["cinematic"]

    pool = out + [e for e in extras if e not in out]
    return [pool[i % len(pool)] for i in range(count)]


_PERMANENT_ERRORS = (401, 402, 403, 404)
_keyless_llm_dead = False


def _ask_llm(instruction: str) -> str:
    """1) Use custom OpenAI/Groq API if configured; 2) Otherwise fallback to Pollinations."""
    global _keyless_llm_dead
    api_key = _get_secret("LLM_API_KEY")
    
    if api_key:
        base = _get_secret("LLM_BASE_URL", "https://api.groq.com/openai/v1").rstrip("/")
        model = _get_secret("LLM_MODEL", "llama-3.3-70b-versatile")
        r = SESSION.post(
            f"{base}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": model, "temperature": 0.7,
                  "messages": [{"role": "user", "content": instruction}]},
            timeout=35,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]

    if _keyless_llm_dead:
        raise RuntimeError("keyless LLM unavailable")

    url = f"https://text.pollinations.ai/{urllib.parse.quote(instruction)}?seed={random.randint(1, 10**6)}"
    try:
        r = SESSION.get(url, timeout=25)
        r.raise_for_status()
        return r.text
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code in _PERMANENT_ERRORS:
            _keyless_llm_dead = True
        raise


def get_video_keywords_from_prompt(prompt: str, style: str = "Cinematic", count: int = 12,
                                   retries: int = 3) -> List[str]:
    """Turn story and style into exact stock video search queries."""
    instruction = (
        "You are a professional film director and video editor. "
        f"The user wants a video based on this prompt: '{prompt}'. "
        f"Visual style preference: '{style}'. "
        f"Break the storyline into exactly {count} chronological visual scenes. "
        "For each scene write a 2-3 word stock video search query in English that a "
        "stock site would actually have (concrete subjects, e.g. 'astronaut walking', "
        "'red planet mars', 'ancient temple drone', 'neon city rain'). "
        "Avoid abstract words, names of people and brands. Do not repeat a query. "
        f"Return ONLY a JSON array of {count} strings. No explanation, no backticks."
    )

    keywords: List[str] = []
    for attempt in range(retries):
        try:
            parsed = _parse_keyword_list(_ask_llm(instruction).strip())
            seen = set()
            keywords = [k for k in parsed if not (k in seen or seen.add(k))]
            if len(keywords) >= max(2, count // 2):
                break
        except requests.HTTPError as e:
            code = e.response.status_code if e.response is not None else "?"
            if code in _PERMANENT_ERRORS:
                break
        except RuntimeError:
            break
        except Exception:
            pass

    if not keywords:
        return _fallback_keywords(prompt, style, count)

    return [keywords[i % len(keywords)] for i in range(count)]


# =====================================================================
# 3. PIXABAY SEARCH + DOWNLOAD
# =====================================================================
def _search_pixabay(query: str, per_page: int = 20) -> list:
    key = _pixabay_key()
    if not key:
        raise RuntimeError("PIXABAY_KEY is missing. Add it to .env or Streamlit Secrets.")
    try:
        r = SESSION.get(
            "https://pixabay.com/api/videos/",
            params={"key": key, "q": query, "video_type": "film",
                    "per_page": per_page, "safesearch": "true"},
            timeout=15,
        )
        r.raise_for_status()
        return r.json().get("hits", [])
    except Exception as e:
        print(f"Pixabay search error for '{query}': {e}")
        return []


def _best_rendition(hit: dict, prefer: str) -> Optional[Tuple[str, dict]]:
    order = ["medium", "small", "large", "tiny"]
    if prefer in order:
        order = order[order.index(prefer):]
    vids = hit.get("videos", {})
    for q in order:
        v = vids.get(q) or {}
        if v.get("url"):
            return q, v
    return None


def _score_hit(hit: dict, portrait: Optional[bool], prefer: str) -> Optional[Tuple[float, str, dict]]:
    rend = _best_rendition(hit, prefer)
    if not rend:
        return None
    quality, v = rend
    w, h = v.get("width", 0) or 0, v.get("height", 0) or 0
    score = 0.0
    if w and h:
        if portrait is not None and (h > w) == portrait:
            score += 50
        score += min(max(w, h), 1920) / 1920 * 30
    dur = hit.get("duration", 0) or 0
    score += min(dur, 15)
    if dur < 3:
        score -= 20
    return score, quality, v


def _queries_for(kw: str) -> List[str]:
    words = kw.split()
    chain = [kw]
    if len(words) > 1:
        chain += [words[-1], words[0]]
    seen = set()
    return [q for q in chain if not (q in seen or seen.add(q))]


def _download_file(url: str, dest: str) -> bool:
    tmp = dest + ".part"
    try:
        with SESSION.get(url, stream=True, timeout=40) as r:
            r.raise_for_status()
            with open(tmp, "wb") as f:
                for chunk in r.iter_content(chunk_size=1024 * 512):
                    f.write(chunk)
        os.replace(tmp, dest)
        return True
    except Exception as e:
        print(f"Download failed ({url}): {e}")
        if os.path.exists(tmp):
            os.remove(tmp)
        return False


def download_real_videos(keywords, folder: str = "temp_videos",
                         aspect_ratio: Optional[str] = None,
                         quality: str = "medium",
                         max_workers: int = 5,
                         progress_callback: ProgressCb = None) -> List[str]:
    """
    Search Pixabay, pick optimal non-duplicate clips, and download concurrently.
    Cached by Pixabay video ID to make re-runs instantaneous.
    """
    os.makedirs(folder, exist_ok=True)
    portrait = None if aspect_ratio is None else (aspect_ratio == "9:16")
    total = max(len(keywords), 1)

    used_ids = set()
    plan: List[Tuple[int, str, str]] = []
    
    for i, kw in enumerate(keywords):
        chosen = None
        for q in _queries_for(kw):
            hits = _search_pixabay(q)
            ranked = []
            for hit in hits:
                if hit.get("id") in used_ids:
                    continue
                scored = _score_hit(hit, portrait, quality)
                if scored:
                    ranked.append((scored[0], hit, scored[1], scored[2]))
            if ranked:
                ranked.sort(key=lambda t: t[0], reverse=True)
                _, hit, q_name, v = ranked[0]
                used_ids.add(hit["id"])
                path = os.path.join(folder, f"pixabay_{hit['id']}_{q_name}.mp4")
                chosen = (i, v["url"], path)
                break
        if chosen:
            plan.append(chosen)
        _report(progress_callback, 0.3 * (i + 1) / total, f"Searching scenes ({i + 1}/{total})")

    done_count = 0

    def fetch(item: Tuple[int, str, str]) -> Tuple[int, Optional[str]]:
        idx, url, path = item
        if os.path.exists(path) and os.path.getsize(path) > 0:
            return idx, path
        return idx, path if _download_file(url, path) else None

    results = {}
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        for idx, path in pool.map(fetch, plan):
            done_count += 1
            if path:
                results[idx] = path
            _report(progress_callback, 0.3 + 0.7 * done_count / max(len(plan), 1),
                    f"Downloaded {done_count}/{len(plan)} clips")

    return [results[i] for i in sorted(results)]


# =====================================================================
# 4. VIDEO ASSEMBLY (Speed-Optimized for Cloud & Desktop)
# =====================================================================
def _fit_to_frame(clip, w: int, h: int):
    """Scale to cover frame, then center crop (no letterbox bars, no distortion)."""
    scale = max(w / clip.w, h / clip.h)
    new_w, new_h = max(w, math.ceil(clip.w * scale)), max(h, math.ceil(clip.h * scale))
    clip = clip.resized((new_w, new_h))
    return clip.cropped(x_center=new_w / 2, y_center=new_h / 2, width=w, height=h)


def assemble_video(video_files, total_duration, output_path, aspect_ratio: str = "9:16",
                   crossfade: float = 0.3,
                   fps: int = 24,
                   music_path: Optional[str] = None,
                   music_volume: float = 0.5,
                   fade_in: float = 0.4,
                   fade_out: float = 0.6,
                   preset: str = "ultrafast",
                   progress_callback: ProgressCb = None) -> bool:
    """
    Concatenate, crop, apply crossfades and export final MP4.
    preset='ultrafast' ensures fast rendering on Streamlit Cloud containers.
    """
    from moviepy import VideoFileClip, AudioFileClip, concatenate_videoclips, vfx, afx

    n = len(video_files)
    if n == 0:
        return False

    # Standard clean resolutions (720p vertical saves massive CPU overhead)
    target_w, target_h = (1280, 720) if aspect_ratio == "16:9" else (720, 1280)

    base = total_duration / n
    t = max(0.0, min(crossfade, base / 3)) if n > 1 else 0.0
    per_clip = (total_duration + t * (n - 1)) / n

    opened, processed = [], []
    final = audio = None
    try:
        for i, path in enumerate(video_files):
            src = VideoFileClip(path)
            opened.append(src)
            clip = src.without_audio()

            if clip.duration < per_clip:
                clip = clip.with_effects([vfx.Loop(duration=per_clip)])
            else:
                clip = clip.subclipped(0, per_clip)

            clip = _fit_to_frame(clip, target_w, target_h)
            if i > 0 and t > 0:
                clip = clip.with_effects([vfx.CrossFadeIn(t)])
            processed.append(clip)
            _report(progress_callback, 0.4 * (i + 1) / n, f"Processing scene {i + 1}/{n}")

        final = concatenate_videoclips(processed, method="compose", padding=-t if t > 0 else 0)
        final = final.subclipped(0, min(final.duration, total_duration))

        fades = []
        if fade_in > 0:
            fades.append(vfx.FadeIn(fade_in))
        if fade_out > 0:
            fades.append(vfx.FadeOut(fade_out))
        if fades:
            final = final.with_effects(fades)

        if music_path and os.path.exists(music_path):
            audio = AudioFileClip(music_path)
            if audio.duration < final.duration:
                audio = audio.with_effects([afx.AudioLoop(duration=final.duration)])
            else:
                audio = audio.subclipped(0, final.duration)
            audio = audio.with_effects([afx.MultiplyVolume(music_volume), afx.AudioFadeOut(1.2)])
            final = final.with_audio(audio)

        _report(progress_callback, 0.5, "Encoding video file...")
        final.write_videofile(
            output_path,
            fps=fps,
            codec="libx264",
            audio_codec="aac" if audio else None,
            preset=preset,
            threads=os.cpu_count() or 4,
            ffmpeg_params=["-pix_fmt", "yuv420p", "-movflags", "+faststart"],
        )
        _report(progress_callback, 1.0, "Ready")
        return True
    finally:
        for c in [final, audio, *processed, *opened]:
            try:
                if c is not None:
                    c.close()
            except Exception:
                pass