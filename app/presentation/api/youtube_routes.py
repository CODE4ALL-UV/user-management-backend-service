from fastapi import APIRouter, HTTPException
import os
from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled
import requests

router = APIRouter(prefix="/api/youtube", tags=["youtube"])


@router.get("/captions")
def get_captions(video_id: str, target: str = "es"):
    """Fetch captions for a YouTube video and optionally translate to target language.
    Returns JSON: {"cues": [{"start": float, "duration": float, "text": str, "translated": str?}, ...]}
    """
    try:
        transcript = YouTubeTranscriptApi().fetch(video_id, languages=("en", "es", "fr", "de"))
    except TranscriptsDisabled:
        raise HTTPException(status_code=404, detail="Transcripts disabled or not available for this video")
    except Exception as e:
        print(f"Transcript fetch error: {e}")
        return {"cues": []}

    cues = []
    for t in transcript:
        cue = {
            "start": getattr(t, "start", 0.0),
            "duration": getattr(t, "duration", 0.0),
            "text": getattr(t, "text", ""),
        }
        cues.append(cue)

    # Optional translation using provider env vars
    provider = os.environ.get("TRANSLATE_PROVIDER", "").lower()
    api_key = os.environ.get("TRANSLATE_API_KEY", "")
    if provider and api_key:
        # Batch translate in groups to avoid large URL lengths
        batch_size = 20
        for i in range(0, len(cues), batch_size):
            batch = cues[i : i + batch_size]
            texts = [c["text"] for c in batch]
            try:
                translations = _translate_batch(provider, api_key, texts, target)
                for j, tr in enumerate(translations):
                    batch[j]["translated"] = tr
            except Exception as e:
                # If translation fails, continue without translated text
                print(f"Translation error: {e}")

    return {"cues": cues}


def _translate_batch(provider: str, api_key: str, texts, target: str):
    if provider == "deepl":
        url = "https://api.deepl.com/v2/translate"
        params = {"auth_key": api_key, "target_lang": target.upper()}
        for t in texts:
            params.setdefault("text", []).append(t)
        res = requests.post(url, data=params, timeout=15)
        res.raise_for_status()
        data = res.json()
        return [x.get("text", "") for x in data.get("translations", [])]
    else:
        # default: Google Translate v2
        url = "https://translation.googleapis.com/language/translate/v2"
        # Build POST with key and q params
        params = {"key": api_key, "target": target}
        # Use form-urlencoded with multiple q fields
        payload = []
        for t in texts:
            payload.append(("q", t))
        res = requests.post(url, params=params, data=payload, timeout=15)
        res.raise_for_status()
        data = res.json()
        translations = [t.get("translatedText", "") for t in data.get("data", {}).get("translations", [])]
        return translations
