# Generates the voice-over lines with ElevenLabs.
#
#   ELEVENLABS_API_KEY=... python promo/tts.py
#
# Writes promo/voice/line_<n>.mp3 for every line of promo/narration.json.

import json
import os
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "voice")


def main():
    key = os.environ["ELEVENLABS_API_KEY"]
    with open(os.path.join(HERE, "narration.json"), encoding="utf-8") as f:
        cfg = json.load(f)
    os.makedirs(OUT, exist_ok=True)
    lines = cfg["lines"]
    url = ("https://api.elevenlabs.io/v1/text-to-speech/%s?output_format=mp3_44100_192"
           % cfg["voice_id"])
    for i, text in enumerate(lines):
        body = {
            "text": text,
            "model_id": cfg["model_id"],
            "voice_settings": {"stability": 0.55, "similarity_boost": 0.8, "style": 0.15},
            "seed": 7,
        }
        if i > 0:
            body["previous_text"] = lines[i - 1]
        if i + 1 < len(lines):
            body["next_text"] = lines[i + 1]
        req = urllib.request.Request(
            url, data=json.dumps(body).encode("utf-8"), method="POST",
            headers={"xi-api-key": key, "Content-Type": "application/json", "Accept": "audio/mpeg"})
        with urllib.request.urlopen(req) as resp:
            data = resp.read()
        path = os.path.join(OUT, "line_%d.mp3" % (i + 1))
        with open(path, "wb") as f:
            f.write(data)
        print(path, len(data))


if __name__ == "__main__":
    main()
