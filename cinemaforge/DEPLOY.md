# CinemaForge — Deployment Guide
# ═══════════════════════════════════════════════════════════════════
# Deploy alongside ReelForge on the same Google VM
# ReelForge runs on port 8000, CinemaForge on port 8001
# ═══════════════════════════════════════════════════════════════════

## FOLDER STRUCTURE
```
/home/ubuntu/
├── reelforge/          ← your existing platform (unchanged)
│   ├── app/
│   │   ├── renderer.py
│   │   ├── models.py
│   │   └── main.py
│   └── ...
│
├── cinemaforge/        ← new platform (this repo)
│   ├── app/
│   │   ├── __init__.py
│   │   ├── parser.py
│   │   ├── tts.py
│   │   ├── alignment.py
│   │   ├── renderer.py
│   │   ├── models.py
│   │   └── main.py
│   ├── assets/         ← per-project uploaded assets
│   │   └── suzy_lamplugh___episode_1/
│   │       ├── cold_open.mp4      ← AI_VIDEO you upload
│   │       ├── victim_intro.jpg   ← STOCK auto-fetched
│   │       ├── diary_entry.jpg    ← AI_IMAGE you upload
│   │       └── ...
│   ├── music/          ← background music tracks
│   │   ├── dark_ambient.mp3
│   │   ├── tension_swell.mp3
│   │   └── tense_ambient.mp3
│   ├── sfx/            ← sound effects
│   │   ├── impact.mp3
│   │   ├── typewriter.mp3
│   │   └── thunder.mp3
│   ├── voices/         ← optional Chatterbox voice refs
│   │   ├── narrator.wav       ← your custom narrator voice
│   │   ├── detective.wav      ← detective character voice
│   │   └── witness.wav
│   ├── output_cinema/  ← rendered videos
│   ├── data/
│   │   └── cinemaforge.db
│   ├── requirements.txt
│   └── run.sh
```

## REQUIREMENTS
```
# Same as ReelForge plus:
fastapi
uvicorn
sqlalchemy
slowapi
moviepy
numpy
requests
torch
torchaudio
chatterbox-tts
faster-whisper      # optional (whisper alignment backend)
```

## ENVIRONMENT VARIABLES (.env)
```bash
CINEMA_USER=admin
CINEMA_PASSWORD=your_password_here
CINEMA_DB_PATH=data/cinemaforge.db
PEXELS_API_KEY=your_pexels_key_here   # free at pexels.com/api

ASSETS_FOLDER=assets
MUSIC_FOLDER=music
SFX_FOLDER=sfx
VOICES_FOLDER=voices
OUTPUT_FOLDER=output_cinema

ALIGN_BACKEND=wav2vec2    # or whisper
TTS_VOICE_REF=voices/narrator.wav   # optional global voice ref

# YouTube upload (same credentials as ReelForge)
YT_CLIENT_SECRET=client_secret.json
YT_CHANNEL_EN=your_english_channel_id
YT_CHANNEL_HI=your_hindi_channel_id
```

## run.sh
```bash
#!/bin/bash
cd /home/ubuntu/cinemaforge
source venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8001 --workers 1
```

## NGINX CONFIG (add to existing nginx conf)
```nginx
# CinemaForge (port 8001)
location /cinema/ {
    proxy_pass http://127.0.0.1:8001/;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_read_timeout 3600;    # long timeout for render jobs
}
```

## SYSTEMD SERVICE
```ini
[Unit]
Description=CinemaForge
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/cinemaforge
ExecStart=/home/ubuntu/cinemaforge/run.sh
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable cinemaforge
sudo systemctl start cinemaforge
sudo systemctl status cinemaforge
```

## PEXELS API KEY (free)
1. Go to pexels.com/api
2. Create free account
3. Generate API key
4. Add to .env as PEXELS_API_KEY

## WORKFLOW (how you use CinemaForge day-to-day)

1. Write your script in the CinemaForge format (see SCRIPT_FORMAT.md)
2. Submit via the web UI
3. Platform auto-fetches all [STOCK] images from Pexels
4. Platform shows you the asset checklist:
   - Which AI images/videos you need to generate (with the exact prompts)
   - Which are already ready
5. Generate AI assets on Seedance/Leonardo → upload via UI
6. Once all assets are green → hit Render
7. Platform:
   - Generates all scene audio via Chatterbox
   - Aligns audio to words
   - Renders each scene with correct background + effects
   - Stitches scenes together
   - Adds outro
   - Auto-generates a 45s Short from the best scene
8. Review outputs → schedule upload to EN + HI channels

## WHAT STAYS THE SAME FROM REELFORGE
- Chatterbox TTS engine
- wav2vec2 forced alignment
- ReelForge motivational shorts format still works (submit via ReelForge)
- YouTube uploader (same credentials)
- All moviepy/ffmpeg render logic (extended, not replaced)

## WHAT IS NEW IN CINEMAFORGE
- Scene-by-scene production model
- [STOCK] | [AI_IMAGE] | [AI_VIDEO] | [USER_VIDEO] asset types
- Pexels auto-fetch for stock assets
- Multi-speaker dialogue with per-character voice refs
- Motion effects: zoom_in | zoom_out | pan_left | pan_right | ken_burns | still
- Auto Short generation from best scene
- Dual channel (EN + HI) upload from single project
- Asset manifest + checklist — rendering blocked until all assets ready
