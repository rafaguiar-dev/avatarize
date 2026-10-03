"""Preparação local de foto e áudio no formato que o HeyGen aceita."""
from __future__ import annotations

import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

Log = Callable[[str], None]

IMAGE_TYPES = {"jpeg": "image/jpeg", "png": "image/png"}
AUDIO_TYPES = {"mp3": "audio/mpeg", "wav": "audio/wav"}

# Limiar (dB) abaixo do qual o trecho conta como silêncio.
SILENCE_LEVELS = {"Suave": -40, "Médio": -32, "Forte": -25}

# MP3 com etiqueta ID3 maior que isso (capas, XMP do Adobe...) é limpo antes do envio.
ID3_LIMIT = 8 * 1024

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def sniff(path: Path) -> str:
    """Formato real pelos primeiros bytes (a extensão do arquivo nem sempre é verdade)."""
    with open(path, "rb") as f:
        h = f.read(32)
    if h[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if h[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if h[:4] == b"RIFF" and h[8:12] == b"WEBP":
        return "webp"
    if h[:4] == b"RIFF" and h[8:12] == b"WAVE":
        return "wav"
    if h[:3] == b"GIF":
        return "gif"
    if h[:2] == b"BM":
        return "bmp"
    if h[:4] in (b"II*\x00", b"MM\x00*"):
        return "tiff"
    if h[:3] == b"ID3" or (len(h) > 1 and h[0] == 0xFF and h[1] & 0xE0 == 0xE0):
        return "mp3"
    if h[:4] == b"OggS":
        return "ogg"
    if h[:4] == b"fLaC":
        return "flac"
    if h[4:8] == b"ftyp":
        brand = h[8:12]
        if brand in (b"avif", b"avis"):
            return "avif"
        if brand in (b"heic", b"heix", b"hevc", b"mif1", b"msf1"):
            return "heic"
        return "m4a"
    return "desconhecido"


def has_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None


def _ffmpeg() -> str:
    exe = shutil.which("ffmpeg")
    if not exe:
        raise RuntimeError("Esta opção precisa do ffmpeg instalado (https://ffmpeg.org/download.html).")
    return exe


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, creationflags=_NO_WINDOW)


def _to_mp3(src: Path, dest: Path, audio_filter: str | None = None) -> bool:
    cmd = [_ffmpeg(), "-y", "-i", str(src), "-map_metadata", "-1", "-map", "a:0"]
    if audio_filter:
        cmd += ["-af", audio_filter]
    cmd += ["-codec:a", "libmp3lame", "-q:a", "2", str(dest)]
    r = _run(cmd)
    return r.returncode == 0 and dest.exists() and dest.stat().st_size > 0


def prepare_image(path: Path, workdir: Path, log: Log) -> tuple[Path, str]:
    kind = sniff(path)
    if kind in IMAGE_TYPES:
        return path, IMAGE_TYPES[kind]
    log(f"Foto em {kind.upper()} — o HeyGen só aceita JPG/PNG. Convertendo...")
    from PIL import Image

    out = workdir / f"{path.stem}.jpg"
    try:
        with Image.open(path) as im:
            im.convert("RGB").save(out, "JPEG", quality=95)
    except Exception as e:
        raise RuntimeError(
            f"Não consegui converter a foto ({kind.upper()}). Abra no editor de imagens e exporte como JPG."
        ) from e
    log("Foto convertida para JPG ✓")
    return out, "image/jpeg"


def id3_size(path: Path) -> int:
    """Tamanho da etiqueta ID3v2 no início do MP3 (0 se não houver)."""
    with open(path, "rb") as f:
        h = f.read(10)
    if len(h) < 10 or h[:3] != b"ID3":
        return 0
    size = (h[6] & 0x7F) << 21 | (h[7] & 0x7F) << 14 | (h[8] & 0x7F) << 7 | (h[9] & 0x7F)
    return 10 + size + (10 if h[5] & 0x10 else 0)


def strip_id3(path: Path, workdir: Path) -> Path:
    tag = id3_size(path)
    data = path.read_bytes()[tag:]
    if not (data[:3] == b"ID3" or (len(data) > 1 and data[0] == 0xFF and data[1] & 0xE0 == 0xE0)):
        raise RuntimeError("Não consegui limpar os metadados do MP3 (arquivo fora do padrão).")
    out = workdir / f"{path.stem}_limpo.mp3"
    out.write_bytes(data)
    return out


def prepare_audio(path: Path, workdir: Path, log: Log) -> tuple[Path, str]:
    kind = sniff(path)
    if kind == "mp3":
        tag = id3_size(path)
        if tag > ID3_LIMIT:
            log(f"MP3 com {tag // 1024} KB de metadados — limpando...")
            path = strip_id3(path, workdir)
            log("Metadados removidos ✓")
        return path, AUDIO_TYPES["mp3"]
    if kind in AUDIO_TYPES:
        return path, AUDIO_TYPES[kind]
    if not has_ffmpeg():
        raise RuntimeError(
            f"Áudio em {kind.upper()} — o HeyGen só aceita MP3 ou WAV. Converta para MP3 (ou instale o ffmpeg)."
        )
    log(f"Áudio em {kind.upper()} — convertendo para MP3...")
    out = workdir / f"{path.stem}.mp3"
    if not _to_mp3(path, out):
        raise RuntimeError(f"O ffmpeg não conseguiu converter o áudio ({kind.upper()}).")
    log("Áudio convertido para MP3 ✓")
    return out, AUDIO_TYPES["mp3"]


def duration(path: Path) -> float | None:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return None
    r = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, creationflags=_NO_WINDOW,
    )
    try:
        return float(r.stdout.strip())
    except ValueError:
        return None


def remove_silences(path: Path, workdir: Path, level: str, log: Log, min_pause: float = 0.35) -> Path:
    """Tira as pausas longas da fala (ffmpeg silenceremove). Devolve um MP3 novo."""
    th = SILENCE_LEVELS.get(level, SILENCE_LEVELS["Médio"])
    filt = (
        f"silenceremove=start_periods=1:start_silence=0:start_threshold={th}dB"
        f":stop_periods=-1:stop_duration={min_pause}:stop_threshold={th}dB:detection=rms"
    )
    log(f"Cortando silêncios (sensibilidade {level})...")
    out = workdir / f"{path.stem}_sem_silencio.mp3"
    if not _to_mp3(path, out, filt):
        raise RuntimeError("Não consegui cortar os silêncios (o ffmpeg falhou).")
    before, after = duration(path), duration(out)
    if before and after:
        log(f"Silêncios cortados: {before:.1f}s → {after:.1f}s (-{max(0.0, before - after):.1f}s) ✓")
    else:
        log("Silêncios cortados ✓")
    return out
