"""Janela do app (pywebview + WebView2) e a ponte entre a página (web/) e o motor (service.py).

A página chama os métodos públicos de `Ponte` por `window.pywebview.api.<método>()`;
o Python avisa mudanças chamando `AV.evento({...})` na página.
A página nunca recebe nem manda caminhos de arquivo: só ids que a ponte guarda.
"""
from __future__ import annotations

import base64
import io
import json
import os
import queue
import sys
import threading
import time
import uuid
import webbrowser
from dataclasses import asdict
from pathlib import Path

import webview
from webview.dom import DOMEventHandler

from . import auth, config, media, service
from .auth import NotConnectedError
from .service import VideoJob

WEB = Path(__file__).resolve().parent / "web"
DEV_URL = "https://github.com/rafaguiar-dev"

IMAGE_KINDS = {"jpeg", "png", "webp", "gif", "bmp", "tiff", "avif", "heic"}
AUDIO_KINDS = {"mp3", "wav", "m4a", "ogg", "flac"}
IMAGE_FILTER = ("Imagens (*.png;*.jpg;*.jpeg;*.webp;*.gif;*.bmp;*.tiff;*.avif;*.heic)", "Todos os arquivos (*.*)")
AUDIO_FILTER = ("Áudios (*.mp3;*.mpeg;*.mpga;*.wav;*.m4a;*.aac;*.ogg;*.opus;*.flac)", "Todos os arquivos (*.*)")
ASPECTS, RESOLUTIONS, EXPRESSIONS = {"9:16", "16:9"}, {"720p", "1080p"}, {"low", "medium", "high"}
PENDING = ("queued", "running")


def _now_ms() -> int:
    return int(time.time() * 1000)


def _size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}".replace(".", ",")
        n /= 1024
    return ""


def _err(e: BaseException) -> str:
    return str(e).strip() or type(e).__name__


def _open(path: Path) -> None:
    if sys.platform == "win32":
        os.startfile(path)  # noqa: S606 - abre no app padrão do Windows
    else:
        webbrowser.open(path.as_uri())


class Ponte:
    def __init__(self) -> None:
        self._window: webview.Window | None = None
        self._lock = threading.RLock()
        self._files: dict[str, Path] = {}
        self._photo: str | None = None
        self._thumbs: dict[str, str | None] = {}
        self._jobs: dict[int, dict] = {}
        self._specs: dict[int, VideoJob] = {}
        self._outputs: dict[int, Path] = {}
        self._queue: queue.Queue[int] = queue.Queue()
        self._seq = 0
        self._out_dir = config.default_output_dir()
        self._connecting = False
        self._drop_ready = False
        threading.Thread(target=self._worker, daemon=True).start()

    # ------------------------------------------------------------ infraestrutura

    def _emit(self, tipo: str, **data) -> None:
        if self._window is None:
            return
        payload = json.dumps({"tipo": tipo, **data}, ensure_ascii=False)
        try:
            self._window.evaluate_js(f"window.AV && AV.evento({payload})")
        except Exception:
            pass

    def _register(self, path: Path) -> str:
        fid = uuid.uuid4().hex[:12]
        with self._lock:
            self._files[fid] = path
        return fid

    def _pending(self) -> int:
        with self._lock:
            return sum(1 for j in self._jobs.values() if j["state"] in PENDING)

    def _dialog(self, kind, types=(), multiple: bool = False) -> list[str]:
        if self._window is None:
            return []
        result = self._window.create_file_dialog(kind, allow_multiple=multiple, file_types=types)
        return [str(p) for p in result] if result else []

    def _photo_info(self, path: Path) -> dict:
        fid = self._register(path)
        info = {"id": fid, "name": path.name, "thumb": None, "info": _size(path.stat().st_size)}
        try:
            from PIL import Image, ImageOps

            with Image.open(path) as im:
                w, h = im.size
                im = ImageOps.exif_transpose(im)
                im.thumbnail((192, 192))
                buf = io.BytesIO()
                im.convert("RGB").save(buf, "JPEG", quality=85)
            info["thumb"] = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
            info["info"] = f"{w}×{h} · {info['info']}"
        except Exception:
            info["info"] += " · sem pré-visualização"
        with self._lock:
            self._photo = fid
            self._thumbs[fid] = info["thumb"]
        return info

    def _audio_info(self, path: Path) -> dict:
        secs = media.duration(path)
        dur = f"{int(secs // 60)}:{int(secs % 60):02d}" if secs else _size(path.stat().st_size)
        return {"id": self._register(path), "name": path.name, "dur": dur}

    # ------------------------------------------------------------ eventos da janela

    def _on_shown(self) -> None:
        """Barra de título escura, no tom do app (Windows 11)."""
        if sys.platform != "win32" or self._window is None:
            return
        try:
            import ctypes

            hwnd = self._window.native.Handle.ToInt32()
            dwm = ctypes.windll.dwmapi
            on, caption = ctypes.c_int(1), ctypes.c_int(0x00220C0A)  # COLORREF de #0A0C22
            dwm.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(on), 4)
            dwm.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(caption), 4)
        except Exception:
            pass

    def _on_loaded(self) -> None:
        if self._drop_ready or self._window is None:
            return
        self._window.dom.document.events.drop += DOMEventHandler(self._on_drop, True, True)
        self._drop_ready = True

    def _on_drop(self, event: dict) -> None:
        files = (event.get("dataTransfer") or {}).get("files") or []
        foto, audios, outros = None, [], 0
        for f in files:
            full = f.get("pywebviewFullPath")
            path = Path(full) if full else None
            if not path or not path.is_file():
                outros += 1
                continue
            kind = media.sniff(path)
            if kind in IMAGE_KINDS and foto is None:
                foto = self._photo_info(path)
            elif kind in AUDIO_KINDS:
                audios.append(self._audio_info(path))
            else:
                outros += 1
        self._emit("drop", foto=foto, audios=audios, outros=outros)

    def _on_closing(self):
        n = self._pending()
        if n and self._window is not None and not self._window.create_confirmation_dialog(
            "Sair do Avatarize?",
            f"Há {n} vídeo(s) na fila ou sendo gerados.\n"
            "Se sair agora, eles param (o que já foi enviado continua na sua conta HeyGen).\n\n"
            "Sair mesmo assim?",
        ):
            return False
        return None

    # ------------------------------------------------------------ API da página: geral e conta

    def init(self) -> dict:
        with self._lock:
            jobs = [dict(j) for j in self._jobs.values()]
        return {"versao": config.APP_VERSION, "conectado": auth.is_connected(), "pasta": str(self._out_dir),
                "ffmpeg": media.has_ffmpeg(), "jobs": jobs}

    def check_account(self) -> None:
        def work() -> None:
            try:
                info = service.whoami(interactive=False)
            except NotConnectedError:
                auth.logout()
                self._emit("conta", estado="fora", msg="Sua sessão expirou. Conecte de novo.")
            except Exception as e:  # sem internet etc.: a sessão existe, deixa usar
                self._emit("conta", estado="ok", conta={"email": None, "plan": None, "aviso": _err(e)})
            else:
                self._emit("conta", estado="ok", conta=info)

        threading.Thread(target=work, daemon=True).start()

    def connect(self, trocar: bool = False) -> dict:
        with self._lock:
            if self._pending():
                return {"erro": "Espere os vídeos da fila terminarem para trocar de conta."}
            if self._connecting:
                return {"ok": True}
            self._connecting = True
        if trocar or auth.is_connected():
            auth.logout()

        def work() -> None:
            try:
                info = service.whoami(log=lambda m: self._emit("status", msg=m))
            except Exception as e:
                self._emit("conta", estado="erro", msg=_err(e))
            else:
                self._emit("conta", estado="ok", conta=info)
            finally:
                self._connecting = False

        threading.Thread(target=work, daemon=True).start()
        return {"ok": True}

    def cancel_connect(self) -> bool:
        auth.cancel_login()
        return True

    def logout(self) -> dict:
        if self._pending():
            return {"erro": "Espere os vídeos da fila terminarem para sair da conta."}
        auth.logout()
        return {"ok": True}

    def open_dev(self) -> None:
        webbrowser.open(DEV_URL)

    # ------------------------------------------------------------ API da página: arquivos

    def pick_photo(self) -> dict | None:
        paths = self._dialog(webview.FileDialog.OPEN, IMAGE_FILTER)
        return self._photo_info(Path(paths[0])) if paths else None

    def pick_audios(self) -> list[dict]:
        return [self._audio_info(Path(p)) for p in self._dialog(webview.FileDialog.OPEN, AUDIO_FILTER, multiple=True)]

    def pick_clone_audio(self) -> dict | None:
        paths = self._dialog(webview.FileDialog.OPEN, AUDIO_FILTER)
        return {"id": self._register(Path(paths[0])), "name": Path(paths[0]).name} if paths else None

    def remove_file(self, fid: str) -> None:
        with self._lock:
            if fid != self._photo:
                self._files.pop(fid, None)

    def pick_out_dir(self) -> str | None:
        paths = self._dialog(webview.FileDialog.FOLDER)
        if not paths:
            return None
        self._out_dir = Path(paths[0])
        return str(self._out_dir)

    def open_folder(self) -> None:
        self._out_dir.mkdir(parents=True, exist_ok=True)
        _open(self._out_dir)

    # ------------------------------------------------------------ API da página: vozes

    def voices(self, motor: str) -> dict:
        try:
            if motor == "__private__":
                found = service.list_voices(private=True)
            else:
                found = service.list_voices(engine=motor or None)
        except Exception as e:
            return {"erro": _err(e)}
        return {"vozes": [asdict(v) for v in found]}

    def clone(self, fid: str, nome: str) -> dict:
        with self._lock:
            path = self._files.get(fid)
        nome = (nome or "").strip()
        if not path or not nome:
            return {"erro": "Preencha o nome e escolha o áudio."}

        def work() -> None:
            try:
                vid = service.clone_voice(path, nome, log=lambda m: self._emit("clone", estado="progresso", msg=m))
            except Exception as e:
                self._emit("clone", estado="erro", msg=_err(e))
            else:
                self._emit("clone", estado="ok", voz={"id": vid, "name": nome, "gender": "", "language": ""})

        threading.Thread(target=work, daemon=True).start()
        return {"ok": True}

    # ------------------------------------------------------------ API da página: fila

    def generate(self, o: dict) -> dict:
        if not auth.is_connected():
            return {"erro": "Conecte sua conta HeyGen primeiro."}
        with self._lock:
            photo = self._files.get(self._photo or "")
            thumb = self._thumbs.get(self._photo or "")
        if not photo:
            return {"erro": "Adicione a foto do avatar."}
        common = {
            "photo": photo,
            "aspect": o.get("formato") if o.get("formato") in ASPECTS else "9:16",
            "resolution": o.get("res") if o.get("res") in RESOLUTIONS else "1080p",
            "expressiveness": o.get("expr") if o.get("expr") in EXPRESSIONS else "medium",
            "motion_prompt": (o.get("movimento") or "").strip() or None,
            "out_dir": self._out_dir,
        }
        if o.get("modo") == "texto":
            texto, voz = (o.get("texto") or "").strip(), o.get("voz") or {}
            if not texto or not voz.get("id"):
                return {"erro": "Escreva o texto e escolha uma voz."}
            specs = [VideoJob(**common, script=texto, voice_id=str(voz["id"]), voice_name=str(voz.get("name") or "voz"))]
        else:
            with self._lock:
                audios = [self._files[i] for i in o.get("audios") or [] if i in self._files]
            if not audios:
                return {"erro": "Adicione o áudio da fala."}
            cut = bool(o.get("corte"))
            if cut and not media.has_ffmpeg():
                return {"erro": "Cortar silêncios precisa do ffmpeg instalado."}
            level = o.get("nivel") if o.get("nivel") in media.SILENCE_LEVELS else "Médio"
            specs = [VideoJob(**common, audio=a, cut_silence=cut, silence_level=level) for a in audios]
        return {"jobs": [self._add_job(s, thumb) for s in specs]}

    def _add_job(self, spec: VideoJob, thumb: str | None) -> dict:
        with self._lock:
            self._seq += 1
            jid = self._seq
            texto = spec.script is not None
            title = f"“{spec.script[:48]}{'…' if len(spec.script) > 48 else ''}”" if texto else spec.audio.stem
            job = {
                "id": jid, "title": title, "photo": spec.photo.name, "voice": spec.voice_name,
                "mode": "texto" if texto else "audio", "aspect": spec.aspect, "resolution": spec.resolution,
                "expr": spec.expressiveness, "steps": service.STEPS_TEXT if texto else service.STEPS_AUDIO,
                "state": "queued", "step": None, "msg": "", "started": None, "finished": None,
                "out": None, "error": None, "thumb": thumb,
            }
            self._jobs[jid] = job
            self._specs[jid] = spec
        self._queue.put(jid)
        return dict(job)

    def retry(self, jid: int) -> dict | None:
        with self._lock:
            job = self._jobs.get(jid)
            if not job or job["state"] != "error":
                return None
            job.update(state="queued", step=None, msg="", error=None, started=None, finished=None)
            snapshot = dict(job)
        self._queue.put(jid)
        return snapshot

    def remove(self, jid: int) -> bool:
        with self._lock:
            job = self._jobs.get(jid)
            if not job or job["state"] == "running":
                return False
            del self._jobs[jid]
            self._specs.pop(jid, None)
            self._outputs.pop(jid, None)
        return True

    def open_video(self, jid: int) -> dict | None:
        with self._lock:
            path = self._outputs.get(jid)
        if not path or not path.exists():
            return {"erro": "O arquivo não está mais na pasta."}
        _open(path)
        return None

    def _update_job(self, jid: int, **changes) -> None:
        with self._lock:
            job = self._jobs.get(jid)
            if not job:
                return
            job.update(changes)
            snapshot = dict(job)
        self._emit("job", job=snapshot)

    def _worker(self) -> None:
        """Uma thread só: os vídeos são gerados um de cada vez, na ordem da fila."""
        while True:
            jid = self._queue.get()
            with self._lock:
                job, spec = self._jobs.get(jid), self._specs.get(jid)
                if not job or not spec or job["state"] != "queued":
                    continue
            self._update_job(jid, state="running", started=_now_ms(), step=None, msg="Iniciando…")
            try:
                out = service.generate_video(
                    spec,
                    log=lambda m, j=jid: self._update_job(j, msg=m),
                    on_step=lambda s, j=jid: self._update_job(j, step=s),
                )
            except Exception as e:
                self._update_job(jid, state="error", error=_err(e), finished=_now_ms(), msg="")
            else:
                with self._lock:
                    self._outputs[jid] = out
                self._update_job(jid, state="done", out=out.name, finished=_now_ms(), msg="")


def run() -> None:
    ponte = Ponte()
    width, height = 1240, 820
    try:
        screen = webview.screens[0]
        width, height = min(width, screen.width - 60), min(height, screen.height - 80)
    except Exception:
        pass
    window = webview.create_window(
        config.APP_NAME, url=str(WEB / "index.html"), js_api=ponte, width=width, height=height,
        min_size=(1000, 640), background_color="#0A0C22",
    )
    ponte._window = window
    window.events.shown += ponte._on_shown
    window.events.loaded += ponte._on_loaded
    window.events.closing += ponte._on_closing
    webview.start(http_server=True, private_mode=True, debug=os.environ.get("AVATARIZE_DEBUG") == "1")
