# Vendored: OpenVoice (MyShell) — MIT License

- Source: upload `OpenVoice-main.zip` (github.com/myshell-ai/OpenVoice), vendored 2026-09-29.
- Role (owner decision): **all voiceovers** — jai, sherlock, peter, company videos. HeyGen is used for rendering only.
- Runs as its own service on **Modal (GPU)**, not inside the Python 3.12 backend: its pins (python 3.9, numpy 1.22, librosa 0.9.1, gradio 3.48) conflict with the backend.
- Uses OpenVoice **V2** + MeloTTS. Checkpoints (`checkpoints_v2_0417.zip`) are downloaded when the Modal image is built — not committed.
- Excluded from vendoring: demo notebooks, `resources/` images and sample mp3s.
- Reached only via the Dispatcher tool `voice.synthesize` (R1, daily spend cap). Only consented reference voices are allowed (see config/skills.yaml `voice_policy`).
