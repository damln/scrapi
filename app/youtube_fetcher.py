import asyncio
import logging
from html import escape as html_escape
from urllib.parse import parse_qs, urlparse

import httpx
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api.proxies import GenericProxyConfig

logger = logging.getLogger(__name__)

YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}
FETCH_TIMEOUT = 30.0

_client: httpx.AsyncClient | None = None


def init_client():
    global _client
    _client = httpx.AsyncClient(timeout=FETCH_TIMEOUT)


async def close_client():
    global _client
    if _client:
        await _client.aclose()
        _client = None


def _get_client() -> httpx.AsyncClient:
    if _client is None:
        raise RuntimeError("youtube_fetcher client not initialized")
    return _client


def is_youtube_url(url: str) -> bool:
    parsed = urlparse(url)
    return (parsed.hostname or "").lower() in YOUTUBE_HOSTS


def extract_video_id(url: str) -> str | None:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if host == "youtu.be":
        return parsed.path.strip("/").split("/", 1)[0] or None
    if host not in YOUTUBE_HOSTS:
        return None
    if parsed.path == "/watch":
        video_ids = parse_qs(parsed.query).get("v", [])
        return video_ids[0] if video_ids else None
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) >= 2 and parts[0] in {"embed", "live", "shorts"}:
        return parts[1]
    return None


def _track_metadata(track) -> dict:
    return {
        "language": track.language,
        "language_code": track.language_code,
        "is_generated": track.is_generated,
        "is_translatable": track.is_translatable,
    }


def _track_priority(track) -> tuple[int, int, str]:
    language_code = track.language_code.lower()
    english = language_code == "en" or language_code.startswith("en-")
    return (0 if english else 1, 1 if track.is_generated else 0, language_code)


def _fetch_transcripts(video_id: str, proxy_url: str) -> dict:
    proxy_config = None
    if proxy_url:
        proxy_config = GenericProxyConfig(http_url=proxy_url, https_url=proxy_url)
    transcript_list = YouTubeTranscriptApi(proxy_config=proxy_config).list(video_id)
    tracks = sorted(transcript_list, key=_track_priority)
    available = [_track_metadata(track) for track in tracks]
    fetched_tracks = []
    errors = []

    for track in tracks:
        try:
            fetched = track.fetch()
        except Exception as exc:
            errors.append(
                {
                    "language_code": track.language_code,
                    "error": exc.__class__.__name__,
                }
            )
            continue

        segments = fetched.to_raw_data()
        text = "\n".join(segment["text"].strip() for segment in segments if segment["text"].strip())
        fetched_tracks.append(
            {
                **_track_metadata(track),
                "text": text,
                "segments": segments,
            }
        )

    return {
        "available": available,
        "tracks": fetched_tracks,
        "errors": errors,
    }


def _format_timestamp(seconds: float) -> str:
    total_seconds = max(0, int(seconds))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _transcript_html(transcript: dict) -> str:
    language = html_escape(transcript["language"])
    paragraphs = "\n".join(
        f'<p data-start="{segment["start"]}">'
        f'<time>[{_format_timestamp(segment["start"])}]</time> {html_escape(segment["text"])}</p>'
        for segment in transcript["segments"]
        if segment["text"].strip()
    )
    return f'<section id="transcript"><h1>Transcript ({language})</h1>{paragraphs}</section>'


async def fetch_youtube(url: str, proxy_url: str = "") -> dict | None:
    """Fetch YouTube oEmbed metadata and every available native transcript track."""
    client = _get_client()
    try:
        resp = await client.get(
            "https://www.youtube.com/oembed",
            params={"url": url, "format": "json"},
        )
        if resp.status_code == 404:
            logger.warning("youtube oEmbed returned 404 for %s (page not found)", url)
            return {"not_found": True, "http_status": 404}

        if resp.status_code != 200:
            logger.warning("youtube oEmbed returned %d for %s", resp.status_code, url)
            return None

        body = resp.json()
        title = body.get("title", "")
        author = body.get("author_name", "")
        thumbnail = body.get("thumbnail_url", "")
        embed_html = body.get("html", "")

        full_title = f"{title} — {author}" if author and title else title
        transcript_result = None
        transcript_error = None
        video_id = extract_video_id(url)
        if video_id:
            try:
                transcript_result = await asyncio.to_thread(_fetch_transcripts, video_id, proxy_url)
            except Exception as exc:
                transcript_error = exc.__class__.__name__
                logger.warning("youtube transcript error for %s: %s", url, exc)
        else:
            transcript_error = "InvalidVideoId"

        primary_transcript = None
        transcript_html = ""
        if transcript_result and transcript_result["tracks"]:
            primary_transcript = transcript_result["tracks"][0]
            transcript_html = _transcript_html(primary_transcript)
        elif transcript_result:
            transcript_error = (
                "TranscriptFetchFailed" if transcript_result["available"] else "TranscriptsDisabledOrUnavailable"
            )

        html = f"""<html>
<head>
<meta property="og:site_name" content="YouTube">
<meta property="og:type" content="video">
<meta property="og:url" content="{html_escape(url)}">
<meta property="og:title" content="{html_escape(title)}">
<meta property="og:image" content="{html_escape(thumbnail)}">
<meta name="author" content="{html_escape(author)}">
<title>{html_escape(full_title)}</title>
</head>
<body>{embed_html}{transcript_html}</body>
</html>"""

        return {
            "html": html.strip(),
            "title": full_title,
            "provider": "youtube",
            "video_id": video_id,
            "transcript": primary_transcript,
            "transcripts": transcript_result,
            "transcript_error": transcript_error,
        }
    except Exception as e:
        logger.warning("youtube oEmbed error for %s: %s", url, e)
        return None
