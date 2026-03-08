"""Generateur de sous-titres word-level via faster-whisper.

Transcrit l'audio voiceover et genere un SRT synchronise mot par mot.
"""

import os


def generate_word_level_srt(audio_path: str, output_srt: str) -> str:
    """Genere un fichier SRT word-level depuis l'audio.

    Utilise faster-whisper (modele small, CPU, int8) pour transcrire
    avec des timestamps par mot.

    Returns:
        Chemin du fichier SRT genere.
    """
    from faster_whisper import WhisperModel

    print("[TIKTOK] Transcription faster-whisper (small, CPU)...")
    model = WhisperModel("small", device="cpu", compute_type="int8")
    segments, _ = model.transcribe(audio_path, language="fr", word_timestamps=True)

    idx = 1
    lines = []
    for seg in segments:
        if not seg.words:
            continue
        for word in seg.words:
            start = _format_srt_time(word.start)
            end = _format_srt_time(word.end)
            text = word.word.strip().upper()
            if text:
                lines.append(f"{idx}\n{start} --> {end}\n{text}\n")
                idx += 1

    with open(output_srt, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"[TIKTOK] SRT genere: {output_srt} ({idx - 1} mots)")
    return output_srt


def _format_srt_time(seconds: float) -> str:
    """Convertit des secondes en format SRT (HH:MM:SS,mmm)."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
