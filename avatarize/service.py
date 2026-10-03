"""Operações de alto nível (bloqueantes) usadas pela interface.

Fluxo do vídeo:
  1. prepara foto/áudio localmente (converte, limpa metadados, corta silêncios)
  2. sobe cada arquivo: create_asset_upload -> PUT na URL assinada -> complete_asset_upload
  3. create_video_from_image (foto + áudio, ou foto + texto + voz) -> video_id
  4. consulta get_video até ficar pronto -> link do MP4
  5. baixa o MP4 para a pasta escolhida
"""
from __future__ import annotations

import asyncio
import json
import re
import tempfile
import time
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeVar

from . import config, media, net
from .auth import NotConnectedError
from .heygen import HeyGenError, call, find, open_session

T = TypeVar("T")
Log = Callable[[str], None]

VIDEO_TIMEOUT_S = 30 * 60
CLONE_TIMEOUT_S = 15 * 60
_DONE = {"completed", "complete", "success", "done", "ready"}
_FAILED = {"failed", "error"}


def _quiet(_msg: str) -> None:
    pass


def _leaf(e: BaseException) -> BaseException:
    """Desembrulha ExceptionGroup (TaskGroup do anyio) até a exceção de verdade."""
    for _ in range(20):
        if isinstance(e, BaseExceptionGroup) and e.exceptions:
            e = e.exceptions[0]
        else:
            break
    return e


def _run(factory: Callable[[], Coroutine[Any, Any, T]]) -> T:
    try:
        return asyncio.run(factory())
    except BaseException as e:  # noqa: BLE001 - convertido em mensagem legível
        leaf = _leaf(e)
        if isinstance(leaf, (NotConnectedError, HeyGenError, net.InsecureURLError)):
            raise leaf from None
        if isinstance(leaf, (KeyboardInterrupt, SystemExit)):
            raise
        raise RuntimeError(str(leaf).strip() or type(leaf).__name__) from leaf


async def _upload(client, path: Path, mime: str, label: str, log: Log) -> dict[str, str]:
    """Sobe um arquivo e devolve a referência que as outras tools aceitam."""
    size = path.stat().st_size
    log(f"Enviando {label} ({path.name}, {size // 1024} KB)...")
    res = await call(client, "create_asset_upload", {"filename": path.name, "contentType": mime, "sizeBytes": size})
    asset_id, upload_url = find(res, "asset_id"), find(res, "upload_url")
    if not asset_id or not upload_url:
        raise HeyGenError(f"resposta inesperada de create_asset_upload: {res}")
    headers = find(res, "upload_headers")
    if not isinstance(headers, dict):
        headers = {"Content-Type": mime}
    status = await asyncio.to_thread(net.put_file, upload_url, path, headers)
    if status not in (200, 201, 204):
        raise HeyGenError(f"upload do arquivo de {label} falhou (HTTP {status})")
    done = await call(client, "complete_asset_upload", {"assetId": asset_id})
    url = find(done, "url")
    log(f"{label.capitalize()} enviado ✓")
    return {"type": "url", "url": url} if url else {"type": "asset_id", "asset_id": str(asset_id)}


# ---------------------------------------------------------------- conta

def whoami(log: Log = _quiet, interactive: bool = True) -> dict[str, str | None]:
    """Devolve email/nome/plano. Com interactive=True abre o navegador para login se precisar."""

    async def go():
        async with open_session(log, interactive=interactive) as client:
            info = await call(client, "get_current_user", {})
        plan = find(info, "plan")
        if isinstance(plan, dict):
            plan = plan.get("name") or plan.get("type")
        return {"email": find(info, "email"), "name": find(info, "first_name", "name"), "plan": plan}

    return _run(go)


# ---------------------------------------------------------------- vozes

@dataclass
class Voice:
    id: str
    name: str
    gender: str = ""
    language: str = ""


def list_voices(engine: str | None = None, private: bool = False, limit: int = 100) -> list[Voice]:
    async def go():
        args: dict[str, Any] = {"limit": min(limit, 100), "type": "private" if private else "public"}
        if engine and not private:
            args["engine"] = engine
        async with open_session() as client:
            res = await call(client, "list_voices", args)
        items = res.get("voices")
        if not isinstance(items, list):
            items = next((v for v in res.values() if isinstance(v, list)), [])
        voices = []
        for v in items:
            if isinstance(v, dict) and (vid := v.get("voice_id") or v.get("id")):
                voices.append(Voice(str(vid), v.get("name") or str(vid), v.get("gender") or "", v.get("language") or ""))
        return voices

    return _run(go)


def clone_voice(audio_path: Path, name: str, log: Log = _quiet) -> str:
    """Clona uma voz a partir de um áudio e espera ficar pronta. Devolve o voice_id."""

    async def go():
        with tempfile.TemporaryDirectory(prefix="avatarize_", ignore_cleanup_errors=True) as tmp:
            audio, mime = media.prepare_audio(Path(audio_path), Path(tmp), log)
            async with open_session(log) as client:
                ref = await _upload(client, audio, mime, "amostra de voz", log)
                log("Enviando para clonagem...")
                res = await call(client, "clone_voice", {"audio": ref, "voiceName": name, "removeBackgroundNoise": True})
                vid = find(res, "voice_clone_id", "voice_id", "id")
                if not vid:
                    raise HeyGenError(f"o HeyGen não devolveu o id da voz: {res}")
                start, last = time.monotonic(), None
                while True:
                    info = await call(client, "get_voice", {"voiceId": vid})
                    status = str(find(info, "status") or "").lower()
                    if status != last:
                        log(f"Clonando voz... ({status or 'processando'})")
                        last = status
                    if status in _DONE:
                        return str(vid)
                    if status in _FAILED:
                        raise HeyGenError(f"clonagem falhou: {find(info, 'error', 'message') or info}")
                    if time.monotonic() - start > CLONE_TIMEOUT_S:
                        raise HeyGenError("tempo esgotado esperando a clonagem")
                    await asyncio.sleep(8)

    return _run(go)


# ---------------------------------------------------------------- vídeo

@dataclass
class VideoJob:
    photo: Path
    audio: Path | None = None          # modo "áudio próprio"
    script: str | None = None          # modo "gerar voz" (texto + voice_id)
    voice_id: str | None = None
    voice_name: str | None = None
    aspect: str = "9:16"
    resolution: str = "1080p"
    expressiveness: str = "medium"     # low | medium | high
    motion_prompt: str | None = None
    voice_speed: float = 1.0
    cut_silence: bool = False
    silence_level: str = "Médio"
    out_dir: Path = field(default_factory=config.default_output_dir)

    @property
    def title(self) -> str:
        return f"{self.photo.stem} + {self.audio.stem if self.audio else 'voz'}"


def _safe_name(text: str, limit: int = 60) -> str:
    return re.sub(r"[^\w\-]+", "_", text, flags=re.UNICODE).strip("_")[:limit] or "video"


async def _wait_video(client, video_id: str, log: Log) -> str:
    start, delay, last = time.monotonic(), 6, None
    while True:
        info = await call(client, "get_video", {"videoId": video_id})
        status = str(find(info, "status") or "").lower()
        url = find(info, "video_url")
        if status and status != last:
            log(f"Status: {status}")
            last = status
        if url and (status in _DONE or not status):
            return str(url)
        if status in _FAILED:
            raise HeyGenError(f"o HeyGen não conseguiu gerar o vídeo: {find(info, 'error', 'message') or info}")
        if time.monotonic() - start > VIDEO_TIMEOUT_S:
            raise HeyGenError("tempo esgotado esperando o vídeo ficar pronto")
        await asyncio.sleep(delay)
        delay = min(delay + 2, 20)


def generate_video(job: VideoJob, log: Log = _quiet) -> Path:
    """Roda o fluxo inteiro e devolve o caminho do MP4 baixado."""
    if not job.script and not job.audio:
        raise ValueError("informe um áudio ou um texto + voz")
    if job.script and not job.voice_id:
        raise ValueError("modo texto precisa de uma voz")

    async def go():
        with tempfile.TemporaryDirectory(prefix="avatarize_", ignore_cleanup_errors=True) as tmp:
            work = Path(tmp)
            photo, photo_mime = media.prepare_image(Path(job.photo), work, log)
            audio = audio_mime = None
            if not job.script:
                src = Path(job.audio)
                if job.cut_silence:
                    src = media.remove_silences(src, work, job.silence_level, log)
                audio, audio_mime = media.prepare_audio(src, work, log)

            async with open_session(log) as client:
                image_ref = await _upload(client, photo, photo_mime, "foto", log)
                body: dict[str, Any] = {
                    "image": image_ref,
                    "resolution": job.resolution,
                    "aspectRatio": job.aspect,
                    "expressiveness": job.expressiveness,
                    "title": job.title,
                }
                if job.motion_prompt:
                    body["motionPrompt"] = job.motion_prompt
                if job.script:
                    body["script"] = job.script
                    body["voiceId"] = job.voice_id
                    if abs(job.voice_speed - 1.0) > 1e-6:
                        body["voiceSettings"] = {"speed": job.voice_speed}
                else:
                    ref = await _upload(client, audio, audio_mime, "áudio", log)
                    if ref["type"] == "url":
                        body["audioUrl"] = ref["url"]
                    else:
                        body["audioAssetId"] = ref["asset_id"]

                log("Criando o vídeo no HeyGen...")
                created = await call(client, "create_video_from_image", body)
                video_id = find(created, "video_id", "id")
                if not video_id:
                    raise HeyGenError(f"o HeyGen não devolveu o id do vídeo: {created}")
                log(f"Vídeo em processamento (id {video_id}). Aguardando...")
                url = await _wait_video(client, str(video_id), log)

        log("Baixando o MP4...")
        dest = Path(job.out_dir) / f"{_safe_name(job.title)}_{video_id}.mp4"
        return await asyncio.to_thread(net.download, url, dest)

    return _run(go)


# ---------------------------------------------------------------- diagnóstico

def dump_tools() -> Path:
    """Lista as tools do MCP do HeyGen (nome, descrição, schema) em tools.json."""

    async def go():
        async with open_session(print, interactive=True) as client:
            res = await client.list_tools()
        tools = [
            {"name": t.name, "description": t.description, "input_schema": getattr(t, "inputSchema", None)}
            for t in getattr(res, "tools", res)
        ]
        out = config.data_dir() / "tools.json"
        out.write_text(json.dumps(tools, indent=2, ensure_ascii=False), encoding="utf-8")
        for t in tools:
            print(f"  - {t['name']}: {(t['description'] or '')[:90]}")
        print(f"\n{len(tools)} tools. Detalhes em {out}")
        return out

    return _run(go)
