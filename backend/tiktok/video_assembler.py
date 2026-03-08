"""Assembleur video TikTok via FFmpeg.

Ken Burns effect + sous-titres word-level faster-whisper + musique de fond.
"""

import asyncio
import os
import time

from PIL import Image, ImageDraw, ImageFont

FFMPEG = "ffmpeg"
FFPROBE = "ffprobe"

WIDTH = 1080
HEIGHT = 1920


async def assemble_video(
    image_paths: list[str],
    audio_path: str,
    scenes: list[dict],
    audio_duration: float,
    music_path: str | None = None,
    output_path: str | None = None,
) -> str:
    """Assemble les images + audio + sous-titres + musique en video TikTok."""
    ts = int(time.time())
    if not output_path:
        output_path = f"/tmp/instafarm/videos/tiktok_{ts}.mp4"
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    scene_durations = _adjust_durations(scenes, audio_duration)

    # 1. Generer les sous-titres SRT word-level depuis l'audio
    srt_path = f"/tmp/instafarm/videos/subs_{ts}.srt"
    word_segments = _generate_srt(audio_path, srt_path)

    # 2. Creer les clips avec sous-titres PIL graves par segment temporel
    clip_paths = []
    current_time = 0.0
    for i, (img_path, duration) in enumerate(zip(image_paths, scene_durations)):
        # Trouver les mots qui tombent dans cette scene
        scene_words = _get_words_in_range(word_segments, current_time, current_time + duration)

        # Creer des sous-clips avec mots differents
        scene_clips = await _create_scene_clips_with_words(
            img_path, scene_words, current_time, duration, i, ts
        )
        clip_paths.extend(scene_clips)
        current_time += duration

    # 3. Concatener tous les clips
    concat_path = f"/tmp/instafarm/videos/concat_{ts}.mp4"
    await _concat_clips(clip_paths, concat_path)

    # 4. Assembler : video + voix + musique optionnelle
    await _final_assembly(concat_path, audio_path, music_path, output_path)

    # Cleanup
    for p in clip_paths + [concat_path, srt_path]:
        try:
            os.remove(p)
        except OSError:
            pass

    if os.path.exists(output_path):
        size_mb = os.path.getsize(output_path) / (1024 * 1024)
        print(f"[TIKTOK] Video finale: {output_path} ({size_mb:.1f} MB)")
        return output_path

    raise RuntimeError("Echec assemblage video")


def _generate_srt(audio_path: str, srt_path: str) -> list[dict]:
    """Genere SRT word-level et retourne les segments."""
    try:
        from faster_whisper import WhisperModel

        print("[TIKTOK] Transcription faster-whisper...")
        model = WhisperModel("small", device="cpu", compute_type="int8")
        segments, _ = model.transcribe(audio_path, language="fr", word_timestamps=True)

        words = []
        srt_lines = []
        idx = 1
        for seg in segments:
            if not seg.words:
                continue
            for w in seg.words:
                text = w.word.strip()
                if text:
                    words.append({"start": w.start, "end": w.end, "text": text})
                    start = _format_srt_time(w.start)
                    end = _format_srt_time(w.end)
                    srt_lines.append(f"{idx}\n{start} --> {end}\n{text.upper()}\n")
                    idx += 1

        with open(srt_path, "w", encoding="utf-8") as f:
            f.write("\n".join(srt_lines))

        print(f"[TIKTOK] SRT: {len(words)} mots transcrits")
        return words

    except Exception as e:
        print(f"[TIKTOK] faster-whisper erreur: {e}, pas de sous-titres word-level")
        return []


def _get_words_in_range(words: list[dict], start: float, end: float) -> list[dict]:
    """Retourne les mots dont le timing tombe dans la plage."""
    return [w for w in words if w["start"] >= start - 0.1 and w["start"] < end]


async def _create_scene_clips_with_words(
    image_path: str,
    words: list[dict],
    scene_start: float,
    scene_duration: float,
    scene_idx: int,
    ts: int,
) -> list[str]:
    """Cree des sous-clips pour une scene, chacun avec un groupe de mots different."""
    is_broll = image_path.lower().endswith(".mp4")

    if not words:
        # Pas de mots : un seul clip sans sous-titre
        clip_path = f"/tmp/instafarm/videos/clip_{scene_idx}_0_{ts}.mp4"
        if is_broll:
            await _trim_broll_clip(image_path, clip_path, scene_duration)
        else:
            await _create_ken_burns_clip(image_path, clip_path, scene_duration)
        return [clip_path]

    # Grouper les mots par paquets de 3-4 pour affichage TikTok-style
    groups = _group_words(words, max_words=4)

    clip_paths = []
    broll_offset = 0.0  # Position dans le B-roll source

    for g_idx, group in enumerate(groups):
        group_start = group[0]["start"]
        group_end = group[-1]["end"]

        # Duree = de debut du premier mot a fin du dernier
        # Avec un minimum de 0.5s et clampe dans la scene
        duration = max(group_end - group_start, 0.5)

        # Si c'est le dernier groupe, etendre jusqu'a la fin de la scene
        if g_idx == len(groups) - 1:
            remaining = (scene_start + scene_duration) - group_start
            duration = max(duration, remaining)

        # Limiter la duree pour ne pas depasser la scene
        max_dur = (scene_start + scene_duration) - group_start
        duration = min(duration, max(max_dur, 0.5))

        clip_path = f"/tmp/instafarm/videos/clip_{scene_idx}_{g_idx}_{ts}.mp4"

        if is_broll:
            # B-roll : decouper une portion du video source
            await _trim_broll_clip(image_path, clip_path, duration, broll_offset)
            broll_offset += duration
        else:
            # Image statique : Ken Burns + sous-titre brule
            text = " ".join(w["text"] for w in group).upper()
            sub_img_path = f"/tmp/instafarm/videos/subimg_{scene_idx}_{g_idx}_{ts}.jpg"
            _burn_subtitle(image_path, text, sub_img_path)

            await _create_ken_burns_clip(sub_img_path, clip_path, duration)

            try:
                os.remove(sub_img_path)
            except OSError:
                pass

        clip_paths.append(clip_path)

    return clip_paths


def _group_words(words: list[dict], max_words: int = 4) -> list[list[dict]]:
    """Groupe les mots par paquets de max_words."""
    groups = []
    for i in range(0, len(words), max_words):
        groups.append(words[i:i + max_words])
    return groups


def _adjust_durations(scenes: list[dict], audio_duration: float) -> list[float]:
    """Ajuste les durees des scenes pour correspondre a l'audio."""
    raw_durations = [s.get("duration_seconds", 8) for s in scenes]
    total_raw = sum(raw_durations)

    if total_raw == 0:
        equal = audio_duration / len(scenes)
        return [equal] * len(scenes)

    ratio = audio_duration / total_raw
    adjusted = [d * ratio for d in raw_durations]

    for i in range(len(adjusted)):
        if adjusted[i] < 2.0:
            adjusted[i] = 2.0

    return adjusted


async def _create_ken_burns_clip(image_path: str, output_path: str, duration: float) -> None:
    """Cree un clip video avec leger zoom."""
    fps = 30
    total_frames = int(duration * fps)
    if total_frames < 1:
        total_frames = 15  # minimum 0.5s

    cmd = [
        FFMPEG, "-y",
        "-loop", "1", "-i", image_path,
        "-vf", (
            f"scale={WIDTH * 2}:{HEIGHT * 2},"
            f"zoompan=z='1+0.0005*in':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
            f":d={total_frames}:s={WIDTH}x{HEIGHT}:fps={fps}"
        ),
        "-t", str(max(duration, 0.5)),
        "-c:v", "libx264", "-preset", "ultrafast",
        "-pix_fmt", "yuv420p",
        "-an",
        output_path,
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        await _create_simple_clip(image_path, output_path, max(duration, 0.5))


async def _trim_broll_clip(
    video_path: str, output_path: str, duration: float, offset: float = 0.0
) -> None:
    """Decoupe un segment du B-roll video source."""
    cmd = [
        FFMPEG, "-y",
        "-ss", str(offset),
        "-i", video_path,
        "-t", str(max(duration, 0.5)),
        "-vf", f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,crop={WIDTH}:{HEIGHT}",
        "-c:v", "libx264", "-preset", "ultrafast",
        "-pix_fmt", "yuv420p", "-r", "30",
        "-an",
        output_path,
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        # Fallback : loop le B-roll si offset depasse
        cmd_loop = [
            FFMPEG, "-y",
            "-stream_loop", "-1",
            "-i", video_path,
            "-t", str(max(duration, 0.5)),
            "-vf", f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,crop={WIDTH}:{HEIGHT}",
            "-c:v", "libx264", "-preset", "ultrafast",
            "-pix_fmt", "yuv420p", "-r", "30",
            "-an",
            output_path,
        ]
        proc2 = await asyncio.create_subprocess_exec(
            *cmd_loop, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        await proc2.communicate()


async def _create_simple_clip(image_path: str, output_path: str, duration: float) -> None:
    """Clip simple sans effet (fallback)."""
    cmd = [
        FFMPEG, "-y",
        "-loop", "1", "-i", image_path,
        "-t", str(duration),
        "-vf", f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease,pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2",
        "-c:v", "libx264", "-preset", "ultrafast",
        "-pix_fmt", "yuv420p", "-r", "30", "-an",
        output_path,
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    await proc.communicate()


async def _concat_clips(clip_paths: list[str], output_path: str) -> None:
    """Concatene les clips."""
    list_path = output_path + ".txt"
    with open(list_path, "w") as f:
        for p in clip_paths:
            f.write(f"file '{p}'\n")

    cmd = [
        FFMPEG, "-y",
        "-f", "concat", "-safe", "0",
        "-i", list_path,
        "-c", "copy",
        output_path,
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    await proc.communicate()
    try:
        os.remove(list_path)
    except OSError:
        pass


def _burn_subtitle(image_path: str, text: str, output_path: str) -> None:
    """Grave un sous-titre style TikTok sur l'image."""
    img = Image.open(image_path).convert("RGB")

    if not text:
        img.save(output_path, "JPEG", quality=90)
        return

    draw = ImageDraw.Draw(img)

    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 64)
    except Exception:
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 64)
        except Exception:
            font = ImageFont.load_default()

    # Position centree en bas
    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    x = (img.width - text_w) // 2
    y = img.height - 300

    # Fond semi-transparent
    padding = 20
    bg = Image.new("RGBA", img.size, (0, 0, 0, 0))
    bg_draw = ImageDraw.Draw(bg)
    bg_draw.rounded_rectangle(
        [x - padding, y - padding, x + text_w + padding, y + text_h + padding],
        radius=12,
        fill=(0, 0, 0, 160),
    )
    img = img.convert("RGBA")
    img = Image.alpha_composite(img, bg).convert("RGB")
    draw = ImageDraw.Draw(img)

    # Contour + texte
    for dx in [-3, 0, 3]:
        for dy in [-3, 0, 3]:
            if dx != 0 or dy != 0:
                draw.text((x + dx, y + dy), text, fill="black", font=font)
    draw.text((x, y), text, fill="white", font=font)

    img.save(output_path, "JPEG", quality=90)


async def _final_assembly(
    video_path: str, audio_path: str, music_path: str | None, output_path: str
) -> None:
    """Assemble video + voix + musique optionnelle."""
    if music_path and os.path.exists(music_path):
        # Mixer voix + musique (musique a -15dB)
        cmd = [
            FFMPEG, "-y",
            "-i", video_path,
            "-i", audio_path,
            "-i", music_path,
            "-filter_complex",
            "[1:a]volume=1.0[voice];[2:a]volume=0.15[music];[voice][music]amix=inputs=2:duration=shortest[aout]",
            "-map", "0:v", "-map", "[aout]",
            "-c:v", "libx264", "-preset", "ultrafast",
            "-c:a", "aac", "-b:a", "192k",
            "-shortest",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            output_path,
        ]
    else:
        cmd = [
            FFMPEG, "-y",
            "-i", video_path,
            "-i", audio_path,
            "-c:v", "libx264", "-preset", "ultrafast",
            "-c:a", "aac", "-b:a", "192k",
            "-shortest",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            output_path,
        ]

    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        error = stderr.decode()[-300:]
        # Fallback sans musique si le mix echoue
        if music_path:
            print(f"[TIKTOK] Mix musique echoue, assemblage sans musique: {error}")
            await _final_assembly(video_path, audio_path, None, output_path)
        else:
            raise RuntimeError(f"FFmpeg assembly failed: {error}")


def _format_srt_time(seconds: float) -> str:
    """Convertit des secondes en format SRT."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
