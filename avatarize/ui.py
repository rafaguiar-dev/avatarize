"""Interface desktop (customtkinter) com fila de vídeos."""
from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
import tkinter.font as tkfont
import traceback
from collections.abc import Callable
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

from . import auth, config, media, service
from .auth import NotConnectedError
from .service import VideoJob, Voice

BG = "#0d0f12"
CARD = "#16191d"
CARD2 = "#1e2227"
EDGE = "#2a2f36"
FIELD = "#101317"
ACCENT = "#7b61ff"
ACCENT_HOVER = "#6a4ff0"
DEEP = "#3b2c7e"
DEEP_HOVER = "#4a3898"
OK = "#3ecf8e"
ERR = "#ff6b6b"
INFO = "#b9a8ff"
TXT = "#eef0f2"
MUTED = "#98a0a8"

EXPRESSIONS = {"Baixa": "low", "Média": "medium", "Alta": "high"}
PRIVATE = "__private__"
MY_VOICES = "⭐ Minhas vozes"
ENGINES = {
    MY_VOICES: PRIVATE,
    "Todas": None,
    "Starfish": "starfish",
    "ElevenLabs": "elevenlabs",
    "Cartesia": "cartesia",
    "Fish": "fish",
    "ByteDance": "bytedance",
    "Panda": "panda",
}
IMG_TYPES = [("Imagens", "*.png *.jpg *.jpeg *.webp *.gif *.bmp *.tiff *.avif *.heic"), ("Todos", "*.*")]
AUD_TYPES = [("Áudio", "*.mp3 *.mpeg *.mpga *.wav *.m4a *.aac *.ogg *.opus *.flac"), ("Todos", "*.*")]

_family = "Segoe UI"


def font(size: int, weight: str = "normal") -> ctk.CTkFont:
    return ctk.CTkFont(family=_family, size=size, weight=weight)


def _short(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def open_path(path: Path) -> None:
    if sys.platform == "win32":
        os.startfile(path)  # noqa: S606 - abre no app padrão do Windows
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


def card(parent, radius: int = 16) -> ctk.CTkFrame:
    return ctk.CTkFrame(parent, fg_color=CARD, corner_radius=radius, border_width=1, border_color=EDGE)


def ghost_button(parent, text: str, command: Callable, width: int = 96, **kw) -> ctk.CTkButton:
    return ctk.CTkButton(parent, text=text, width=width, command=command, fg_color="transparent", border_width=1,
                         border_color=EDGE, hover_color=CARD2, corner_radius=14, **kw)


def segmented(parent, values: list[str], command: Callable, width: int | None = None) -> ctk.CTkSegmentedButton:
    kw = {"width": width} if width else {}
    return ctk.CTkSegmentedButton(parent, values=values, command=command, selected_color=ACCENT,
                                  selected_hover_color=ACCENT_HOVER, unselected_color=CARD2,
                                  unselected_hover_color=EDGE, text_color=TXT, corner_radius=14,
                                  font=font(12, "bold"), **kw)


class JobCard:
    """Uma linha da fila."""

    def __init__(self, parent, jid: int, job: VideoJob):
        self.job = job
        self.state = "queued"
        self.frame = ctk.CTkFrame(parent, fg_color=CARD2, corner_radius=14, border_width=1, border_color=EDGE)
        self.frame.pack(fill="x", padx=8, pady=5)
        top = ctk.CTkFrame(self.frame, fg_color="transparent")
        top.pack(fill="x", padx=12, pady=(9, 2))
        ctk.CTkLabel(top, text=f"#{jid}", font=font(13, "bold"), text_color=ACCENT).pack(side="left")
        source = f"✍️ {job.voice_name or 'voz'}" if job.script else job.audio.name
        desc = f"{_short(job.photo.name, 28)}  +  {_short(source, 32)}  ·  {job.aspect} · {job.resolution}"
        ctk.CTkLabel(top, text=desc, font=font(11), text_color=TXT, anchor="w").pack(side="left", padx=10)
        self.open_btn = ctk.CTkButton(top, text="Abrir", width=64, height=26, fg_color=DEEP, hover_color=DEEP_HOVER)
        self.status = ctk.CTkLabel(self.frame, text="⏳ Na fila", font=font(12), text_color=MUTED, anchor="w",
                                   justify="left", wraplength=620)
        self.status.pack(anchor="w", padx=14, pady=(0, 9))

    @property
    def pending(self) -> bool:
        return self.state in ("queued", "running")

    def progress(self, msg: str) -> None:
        self.state = "running"
        self.status.configure(text=f"⚙️ {_short(msg, 150)}", text_color=MUTED)

    def done(self, path: Path) -> None:
        self.state = "done"
        self.status.configure(text=f"✅ Pronto — {path.name}", text_color=OK)
        self.open_btn.configure(command=lambda: open_path(path))
        self.open_btn.pack(side="right")

    def fail(self, msg: str) -> None:
        self.state = "failed"
        self.status.configure(text=f"❌ {_short(msg, 300)}", text_color=ERR)


class App(ctk.CTk):
    def __init__(self) -> None:
        super().__init__(fg_color=BG)
        global _family
        families = set(tkfont.families(self))
        _family = next((f for f in ("Segoe UI Variable Text", "Segoe UI", "Inter") if f in families), "TkDefaultFont")

        self.title(f"{config.APP_NAME}")
        self._set_icon()
        self._fit_window(820, 920)

        self.photo: Path | None = None
        self.audios: list[Path] = []
        self.out_dir = config.default_output_dir()
        self.mode = "file"
        self.aspect, self.resolution, self.expressiveness = "9:16", "1080p", "medium"
        self.silence_level = "Médio"
        self.voice: Voice | None = None
        self.voices: list[Voice] = []
        self.voices_key: str | None = None
        self.voices_loading = False
        self.voices_cache: dict[str, list[Voice]] = {}
        self.picker: ctk.CTkToplevel | None = None

        self._ui_calls: queue.Queue = queue.Queue()
        self._work: queue.Queue[int] = queue.Queue()
        self.jobs: dict[int, JobCard] = {}
        self._job_seq = 0

        self._build()
        self._refresh_connection(check_account=True)
        threading.Thread(target=self._job_worker, daemon=True).start()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._pump_job = self.after(80, self._pump)

    # ------------------------------------------------------------ infraestrutura

    def _set_icon(self) -> None:
        try:
            if sys.platform == "win32":
                self.iconbitmap(str(config.ASSETS / "icon.ico"))
            else:
                self._icon = tk.PhotoImage(file=str(config.ASSETS / "icon.png"))
                self.iconphoto(True, self._icon)
        except Exception:
            pass

    def _fit_window(self, width: int, height: int) -> None:
        try:
            scale = ctk.ScalingTracker.get_window_scaling(self) or 1.0
        except Exception:
            scale = 1.0
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        w = min(width, int(sw / scale) - 60)
        h = min(height, int(sh / scale) - 110)
        # Tamanho em unidades lógicas (o CTk escala); posição em pixels reais.
        x = max(0, int((sw - w * scale) / 2))
        y = max(0, int((sh - h * scale) / 2) - int(30 * scale))
        self.geometry(f"{w}x{h}+{x}+{y}")
        self.minsize(min(640, w), min(560, h))

    def on_ui(self, fn: Callable, *args) -> None:
        """Agenda fn(*args) na thread da interface (Tk não aceita chamadas de outras threads)."""
        self._ui_calls.put((fn, args))

    def _pump(self) -> None:
        try:
            while True:
                fn, args = self._ui_calls.get_nowait()
                try:
                    fn(*args)
                except tk.TclError:
                    pass  # janela/diálogo já foi fechado
                except Exception:
                    traceback.print_exc()
        except queue.Empty:
            pass
        self._pump_job = self.after(80, self._pump)

    def background(self, work: Callable, done: Callable | None = None, fail: Callable | None = None) -> None:
        def run() -> None:
            try:
                result = work()
            except Exception as e:  # noqa: BLE001 - vai para a interface
                if fail:
                    self.on_ui(fail, e)
            else:
                if done:
                    self.on_ui(done, result)

        threading.Thread(target=run, daemon=True).start()

    def _status(self, text: str, color: str = MUTED) -> None:
        self.status_lbl.configure(text=_short(text, 120), text_color=color)

    def _dialog(self, title: str, geometry: str) -> ctk.CTkToplevel:
        dlg = ctk.CTkToplevel(self)
        dlg.title(title)
        w, h = (int(n) for n in geometry.split("x"))
        try:
            scale = ctk.ScalingTracker.get_window_scaling(self) or 1.0
        except Exception:
            scale = 1.0
        x = self.winfo_rootx() + max(0, int((self.winfo_width() - w * scale) / 2))
        y = self.winfo_rooty() + max(0, int((self.winfo_height() - h * scale) / 3))
        dlg.geometry(f"{geometry}+{x}+{y}")
        dlg.configure(fg_color=BG)
        dlg.transient(self)

        def focus() -> None:
            try:
                dlg.lift()
                dlg.focus_force()
                dlg.grab_set()
            except tk.TclError:
                pass

        dlg.after(150, focus)
        return dlg

    # ------------------------------------------------------------ layout

    def _build(self) -> None:
        foot = ctk.CTkFrame(self, fg_color=CARD, corner_radius=0)
        foot.pack(side="bottom", fill="x")
        ctk.CTkButton(foot, text="📂 Abrir pasta dos vídeos", height=30, fg_color=CARD2, hover_color=EDGE,
                      command=self._open_out_dir).pack(side="left", padx=16, pady=8)
        self.status_lbl = ctk.CTkLabel(foot, text="Pronto.", font=font(11), text_color=MUTED)
        self.status_lbl.pack(side="right", padx=16)

        self.body = ctk.CTkScrollableFrame(self, fg_color=BG, corner_radius=0, scrollbar_button_color=EDGE,
                                           scrollbar_button_hover_color="#3a4048")
        self.body.pack(fill="both", expand=True)

        head = ctk.CTkFrame(self.body, fg_color="transparent")
        head.pack(fill="x", padx=26, pady=(20, 2))
        try:
            from PIL import Image

            logo = ctk.CTkImage(Image.open(config.ASSETS / "icon.png"), size=(52, 52))
            ctk.CTkLabel(head, text="", image=logo).pack(side="left", padx=(0, 14))
        except Exception:
            pass
        titles = ctk.CTkFrame(head, fg_color="transparent")
        titles.pack(side="left", fill="x")
        ctk.CTkLabel(titles, text=config.APP_NAME, font=font(26, "bold"), text_color=TXT).pack(anchor="w")
        ctk.CTkLabel(titles, text="Foto + áudio (ou texto) → vídeo com avatar, direto na sua conta HeyGen",
                     font=font(12), text_color=MUTED).pack(anchor="w")

        self._build_connection()
        self._build_composer()
        self._build_output()
        self._build_queue()

    def _build_connection(self) -> None:
        bar = card(self.body)
        bar.pack(fill="x", padx=26, pady=(14, 0))
        inner = ctk.CTkFrame(bar, fg_color="transparent")
        inner.pack(fill="x", padx=14, pady=10)
        self.conn_dot = ctk.CTkLabel(inner, text="●", font=font(16), text_color=ERR)
        self.conn_dot.pack(side="left", padx=(0, 8))
        self.conn_label = ctk.CTkLabel(inner, text="Não conectado", font=font(12), text_color=TXT)
        self.conn_label.pack(side="left")
        self.logout_btn = ghost_button(inner, "Sair", self._on_logout, 64, height=30)
        self.logout_btn.pack(side="right")
        self.conn_btn = ghost_button(inner, "Conectar HeyGen", self._on_connect, 150, height=30)
        self.conn_btn.pack(side="right", padx=(0, 8))

    def _field_row(self, parent, title: str) -> ctk.CTkFrame:
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=18, pady=(12, 0))
        ctk.CTkLabel(row, text=title, font=font(10, "bold"), text_color=MUTED, width=92, anchor="w").pack(side="left")
        return row

    def _file_row(self, parent, emoji: str, title: str, empty: str, command: Callable) -> ctk.CTkLabel:
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=(14, 0))
        ctk.CTkLabel(row, text=emoji, font=font(22)).pack(side="left", padx=(2, 10))
        col = ctk.CTkFrame(row, fg_color="transparent")
        col.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(col, text=title, font=font(13, "bold"), anchor="w").pack(anchor="w")
        value = ctk.CTkLabel(col, text=empty, font=font(12), text_color=MUTED, anchor="w")
        value.pack(anchor="w")
        ghost_button(row, "Escolher", command, 88).pack(side="right")
        return value

    def _build_composer(self) -> None:
        box = card(self.body, radius=20)
        box.pack(fill="x", padx=26, pady=(14, 0))

        self.photo_value = self._file_row(box, "🖼️", "Foto do avatar", "Nenhuma foto", self._pick_photo)

        row = self._field_row(box, "ÁUDIO")
        self.mode_sel = segmented(row, ["🔊 Áudio próprio", "✍️ Gerar voz"], self._on_mode)
        self.mode_sel.set("🔊 Áudio próprio")
        self.mode_sel.pack(side="left")

        holder = ctk.CTkFrame(box, fg_color="transparent")
        holder.pack(fill="x", padx=3)
        self.audio_panel = ctk.CTkFrame(holder, fg_color="transparent")
        self.audio_value = self._file_row(self.audio_panel, "🔊", "Áudio da fala (pode escolher vários)",
                                          "Nenhum áudio", self._pick_audio)
        self._build_silence_row(self.audio_panel)
        self.audio_panel.pack(fill="x")
        self.tts_panel = self._build_tts(holder)

        row = self._field_row(box, "FORMATO")
        self.aspect_sel = segmented(row, ["9:16", "16:9"], lambda v: setattr(self, "aspect", v), 130)
        self.aspect_sel.set("9:16")
        self.aspect_sel.pack(side="left")
        self.res_sel = segmented(row, ["720p", "1080p"], lambda v: setattr(self, "resolution", v), 150)
        self.res_sel.set("1080p")
        self.res_sel.pack(side="left", padx=(12, 0))
        ctk.CTkLabel(row, text="1080p usa mais crédito", font=font(11), text_color=MUTED).pack(side="left", padx=10)

        row = self._field_row(box, "EXPRESSÃO")
        self.expr_sel = segmented(row, list(EXPRESSIONS), lambda v: setattr(self, "expressiveness", EXPRESSIONS[v]), 210)
        self.expr_sel.set("Média")
        self.expr_sel.pack(side="left")
        ctk.CTkLabel(row, text="quanto o avatar se mexe", font=font(11), text_color=MUTED).pack(side="left", padx=10)

        row = self._field_row(box, "MOVIMENTO")
        self.motion_entry = ctk.CTkEntry(row, placeholder_text="opcional — ex: lean in, look at camera, smile",
                                         fg_color=FIELD, border_color=EDGE, corner_radius=10)
        self.motion_entry.pack(side="left", fill="x", expand=True)

        self.generate_btn = ctk.CTkButton(box, text="Gerar vídeo  →", height=48, font=font(15, "bold"),
                                          fg_color=ACCENT, hover_color=ACCENT_HOVER, corner_radius=24,
                                          command=self._on_generate)
        self.generate_btn.pack(fill="x", padx=18, pady=(16, 18))

    def _build_silence_row(self, parent) -> None:
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=(10, 0))
        self.cut_var = ctk.BooleanVar(value=False)
        ctk.CTkSwitch(row, text="✂️  Cortar silêncios", variable=self.cut_var, command=self._on_cut_toggle,
                      progress_color=ACCENT, font=font(12, "bold")).pack(side="left")
        self.silence_sel = segmented(row, list(media.SILENCE_LEVELS), lambda v: setattr(self, "silence_level", v), 210)
        self.silence_sel.set("Médio")
        self.silence_sel.configure(state="disabled")
        self.silence_sel.pack(side="left", padx=12)
        self.silence_hint = ctk.CTkLabel(row, text="remove as pausas longas da fala", font=font(11), text_color=MUTED)
        self.silence_hint.pack(side="left")

    def _build_tts(self, parent) -> ctk.CTkFrame:
        box = ctk.CTkFrame(parent, fg_color=CARD2, corner_radius=16, border_width=1, border_color=EDGE)
        row = ctk.CTkFrame(box, fg_color="transparent")
        row.pack(fill="x", padx=12, pady=(10, 4))
        ctk.CTkLabel(row, text="Motor", font=font(12, "bold")).pack(side="left")
        self.engine_menu = ctk.CTkOptionMenu(row, values=list(ENGINES), width=150, fg_color=CARD,
                                             button_color=ACCENT, button_hover_color=ACCENT_HOVER,
                                             command=lambda _v: self._load_voices())
        self.engine_menu.set(MY_VOICES)
        self.engine_menu.pack(side="left", padx=(8, 14))
        ctk.CTkLabel(row, text="Voz", font=font(12, "bold")).pack(side="left")
        self.voice_btn = ctk.CTkButton(row, text="Escolher voz…", width=240, anchor="w", fg_color=CARD,
                                       hover_color=EDGE, command=self._open_voice_picker)
        self.voice_btn.pack(side="left", padx=8)

        ctk.CTkLabel(box, text="Texto que o avatar vai falar", font=font(12, "bold"), anchor="w").pack(
            anchor="w", padx=14, pady=(6, 2))
        self.script_box = ctk.CTkTextbox(box, height=110, corner_radius=8, fg_color=FIELD, text_color=TXT,
                                         font=font(12), wrap="word")
        self.script_box.pack(fill="x", padx=12, pady=(0, 8))

        row = ctk.CTkFrame(box, fg_color="transparent")
        row.pack(fill="x", padx=12, pady=(0, 10))
        ctk.CTkButton(row, text="🎤 Clonar minha voz", width=160, fg_color=DEEP, hover_color=DEEP_HOVER,
                      command=self._open_clone_dialog).pack(side="left")
        ctk.CTkLabel(row, text=f"clona uma vez; depois ela aparece em '{MY_VOICES}'", font=font(11),
                     text_color=MUTED).pack(side="left", padx=10)
        return box

    def _build_output(self) -> None:
        box = card(self.body)
        box.pack(fill="x", padx=26, pady=(12, 0))
        inner = ctk.CTkFrame(box, fg_color="transparent")
        inner.pack(fill="x", padx=14, pady=10)
        ctk.CTkLabel(inner, text="💾 Salvar em:", font=font(12, "bold")).pack(side="left")
        self.dest_value = ctk.CTkLabel(inner, text=str(self.out_dir), font=font(12), text_color=INFO)
        self.dest_value.pack(side="left", padx=8)
        ghost_button(inner, "Procurar", self._pick_out_dir, 96).pack(side="right")

    def _build_queue(self) -> None:
        head = ctk.CTkFrame(self.body, fg_color="transparent")
        head.pack(fill="x", padx=28, pady=(16, 4))
        ctk.CTkLabel(head, text="Fila", font=font(15, "bold")).pack(side="left")
        self.count_lbl = ctk.CTkLabel(head, text="0 na fila", font=font(12), text_color=MUTED)
        self.count_lbl.pack(side="right")
        self.queue_box = ctk.CTkFrame(self.body, fg_color=FIELD, corner_radius=16, border_width=1, border_color=EDGE)
        self.queue_box.pack(fill="x", padx=26, pady=(0, 16))
        self.empty_lbl = ctk.CTkLabel(self.queue_box, font=font(12), text_color=MUTED,
                                      text="A fila está vazia.\nEscolha a foto + áudio (ou texto) e clique em Gerar vídeo.")
        self.empty_lbl.pack(pady=30)

    # ------------------------------------------------------------ conexão

    def _pending(self) -> int:
        return sum(1 for c in self.jobs.values() if c.pending)

    def _reset_voices(self) -> None:
        self.voices_cache.clear()
        self.voices, self.voices_key, self.voice = [], None, None
        self.voice_btn.configure(text="Escolher voz…")

    def _refresh_connection(self, check_account: bool = False) -> None:
        on = auth.is_connected()
        self.conn_dot.configure(text_color=OK if on else ERR)
        self.conn_label.configure(text="Conectado" if on else "Não conectado")
        self.conn_btn.configure(state="normal", text="Trocar conta" if on else "Conectar HeyGen")
        self.logout_btn.configure(state="normal" if on else "disabled")
        if on and check_account:
            self.conn_label.configure(text="Conectado — confirmando a conta...")
            self.background(lambda: service.whoami(interactive=False), self._on_connected, self._on_check_failed)

    def _on_connect(self) -> None:
        if self._pending():
            self._status("Espere a fila terminar para trocar de conta.", ERR)
            return
        if auth.is_connected():
            auth.logout()
            self._reset_voices()
        self.conn_btn.configure(state="disabled", text="Conectando...")
        self.logout_btn.configure(state="disabled")
        self.conn_dot.configure(text_color=INFO)
        self.conn_label.configure(text="Abrindo o navegador para login...")
        self.background(lambda: service.whoami(log=lambda m: self.on_ui(self._status, m, MUTED)),
                         self._on_connected, self._on_connect_failed)

    def _on_connected(self, info: dict) -> None:
        email, plan = info.get("email") or "conta HeyGen", info.get("plan")
        self.conn_dot.configure(text_color=OK)
        self.conn_label.configure(text=f"Conectado: {email}" + (f"  ·  plano {plan}" if plan else ""))
        self.conn_btn.configure(state="normal", text="Trocar conta")
        self.logout_btn.configure(state="normal")
        self._status("Conta HeyGen conectada.", OK)
        if self.mode == "tts":
            self._load_voices(force=True)

    def _on_connect_failed(self, e: Exception) -> None:
        self._refresh_connection()
        self.conn_dot.configure(text_color=ERR)
        self.conn_label.configure(text=_short(f"Falha ao conectar: {e}", 110))

    def _on_check_failed(self, e: Exception) -> None:
        if isinstance(e, NotConnectedError):
            auth.logout()
            self._refresh_connection()
            self.conn_label.configure(text="Sessão expirada — clique em Conectar HeyGen.")
        else:
            self.conn_label.configure(text=_short(f"Conectado (sem confirmar a conta: {e})", 110))

    def _on_logout(self) -> None:
        if self._pending():
            self._status("Espere a fila terminar para sair da conta.", ERR)
            return
        auth.logout()
        self._reset_voices()
        self._refresh_connection()
        self.conn_label.configure(text="Desconectado. Conecte para usar outra conta.")

    # ------------------------------------------------------------ seleção de arquivos

    def _pick_photo(self) -> None:
        fp = filedialog.askopenfilename(title="Escolha a foto do avatar", filetypes=IMG_TYPES)
        if fp:
            self.photo = Path(fp)
            self.photo_value.configure(text=self.photo.name, text_color=TXT)

    def _pick_audio(self) -> None:
        fps = filedialog.askopenfilenames(title="Escolha o(s) áudio(s)", filetypes=AUD_TYPES)
        if fps:
            self.audios = [Path(p) for p in fps]
            text = self.audios[0].name if len(self.audios) == 1 else f"{len(self.audios)} áudios — um vídeo para cada"
            self.audio_value.configure(text=text, text_color=TXT)

    def _pick_out_dir(self) -> None:
        d = filedialog.askdirectory(title="Pasta onde salvar os vídeos", initialdir=str(self.out_dir))
        if d:
            self.out_dir = Path(d)
            self.dest_value.configure(text=str(self.out_dir))

    def _open_out_dir(self) -> None:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        open_path(self.out_dir)

    def _on_cut_toggle(self) -> None:
        on = bool(self.cut_var.get())
        self.silence_sel.configure(state="normal" if on else "disabled")
        if on and not media.has_ffmpeg():
            self.silence_hint.configure(text="precisa do ffmpeg instalado neste PC", text_color=ERR)
        else:
            self.silence_hint.configure(text="remove as pausas longas da fala", text_color=MUTED)

    def _on_mode(self, value: str) -> None:
        self.mode = "tts" if "Gerar" in value else "file"
        if self.mode == "tts":
            self.audio_panel.pack_forget()
            self.tts_panel.pack(fill="x", padx=16, pady=(12, 0))
            if not self.voices and not self.voices_loading:
                self._load_voices()
        else:
            self.tts_panel.pack_forget()
            self.audio_panel.pack(fill="x")

    # ------------------------------------------------------------ vozes

    def _load_voices(self, force: bool = False) -> None:
        engine = ENGINES.get(self.engine_menu.get())
        key = engine or "all"
        if force:
            self.voices_cache.pop(key, None)
        if key in self.voices_cache:
            self._show_voices(key, self.voices_cache[key])
            return
        if not auth.is_connected():
            self._show_voices(key, [])
            return
        self.voices_key, self.voices_loading = key, True
        self._render_voice_rows()

        def work() -> list[Voice]:
            if engine == PRIVATE:
                return service.list_voices(private=True)
            return service.list_voices(engine=engine)

        def done(voices: list[Voice]) -> None:
            self.voices_cache[key] = voices
            if self.voices_key == key:
                self._show_voices(key, voices)

        def fail(e: Exception) -> None:
            if self.voices_key == key:
                self._show_voices(key, [])
            self._status(f"Vozes: {e}", ERR)

        self.background(work, done, fail)

    def _show_voices(self, key: str, voices: list[Voice]) -> None:
        self.voices, self.voices_key, self.voices_loading = voices, key, False
        self._render_voice_rows()

    def _open_voice_picker(self) -> None:
        if self.picker and self.picker.winfo_exists():
            self.picker.lift()
            return
        dlg = self._dialog("Escolher voz", "560x620")
        top = ctk.CTkFrame(dlg, fg_color="transparent")
        top.pack(fill="x", padx=14, pady=(14, 6))
        self.voice_search = ctk.CTkEntry(top, placeholder_text="🔎 Pesquisar voz...")
        self.voice_search.pack(side="left", fill="x", expand=True)
        self.voice_search.bind("<KeyRelease>", lambda _e: self._render_voice_rows())
        ghost_button(top, "↻ Atualizar", lambda: self._load_voices(force=True), 100).pack(side="right", padx=(8, 0))
        self.voice_list = ctk.CTkScrollableFrame(dlg, fg_color=FIELD, corner_radius=10)
        self.voice_list.pack(fill="both", expand=True, padx=14, pady=(4, 14))
        self.picker = dlg
        if not self.voices and not self.voices_loading:
            self._load_voices()
        self._render_voice_rows()

    def _render_voice_rows(self) -> None:
        if not (self.picker and self.picker.winfo_exists()):
            return
        for w in self.voice_list.winfo_children():
            w.destroy()

        def note(text: str) -> None:
            ctk.CTkLabel(self.voice_list, text=text, text_color=MUTED).pack(pady=24)

        if self.voices_loading:
            return note("Carregando vozes...")
        if not auth.is_connected():
            return note("Conecte sua conta HeyGen para ver as vozes.")
        query = self.voice_search.get().strip().lower()
        star = "⭐ " if self.voices_key == PRIVATE else ""
        shown = 0
        for v in self.voices:
            if query and query not in v.name.lower():
                continue
            gender = {"male": "♂", "female": "♀"}.get(v.gender.lower(), "")
            extra = "   ".join(x for x in (gender, v.language) if x)
            ctk.CTkButton(self.voice_list, text=f"{star}{v.name}   {extra}".rstrip(), anchor="w", height=34,
                          fg_color=CARD2, hover_color=EDGE,
                          command=lambda vv=v: self._select_voice(vv)).pack(fill="x", padx=6, pady=2)
            shown += 1
            if shown >= 200:
                break
        if not shown:
            note("Nenhuma voz encontrada." if query else "Nenhuma voz aqui. Clone uma voz ou troque o Motor.")

    def _select_voice(self, voice: Voice) -> None:
        self.voice = voice
        self.voice_btn.configure(text=_short(voice.name, 34), text_color=TXT)
        if self.picker and self.picker.winfo_exists():
            self.picker.destroy()

    def _open_clone_dialog(self) -> None:
        if not auth.is_connected():
            self._status("Conecte no HeyGen antes de clonar uma voz.", ERR)
            return
        dlg = self._dialog("Clonar voz", "470x300")
        ctk.CTkLabel(dlg, text="🎤 Clonar voz", font=font(18, "bold")).pack(pady=(16, 2))
        ctk.CTkLabel(dlg, text="Envie um áudio limpo só com a voz (30 s a 2 min funciona bem).",
                     font=font(11), text_color=MUTED).pack()
        name_entry = ctk.CTkEntry(dlg, placeholder_text="Nome da voz (ex: Voz Rafa)", width=300)
        name_entry.pack(pady=(12, 6))
        picked: dict[str, Path | None] = {"path": None}
        pick_lbl = ctk.CTkLabel(dlg, text="Nenhum áudio selecionado", font=font(11), text_color=MUTED)

        def pick() -> None:
            fp = filedialog.askopenfilename(parent=dlg, title="Áudio da voz", filetypes=AUD_TYPES)
            if fp:
                picked["path"] = Path(fp)
                pick_lbl.configure(text=Path(fp).name, text_color=TXT)

        ghost_button(dlg, "Escolher áudio", pick, 140).pack()
        pick_lbl.pack(pady=(4, 6))
        status = ctk.CTkLabel(dlg, text="", font=font(11), text_color=INFO, wraplength=420)
        btn = ctk.CTkButton(dlg, text="Clonar", width=140, fg_color=ACCENT, hover_color=ACCENT_HOVER)

        def go() -> None:
            voice_name, path = name_entry.get().strip(), picked["path"]
            if not voice_name or not path:
                status.configure(text="Preencha o nome e escolha o áudio.", text_color=ERR)
                return
            btn.configure(state="disabled", text="Clonando...")

            def progress(msg: str) -> None:
                self.on_ui(lambda: status.configure(text=_short(msg, 120), text_color=INFO))

            def done(_voice_id: str) -> None:
                self.voices_cache.pop(PRIVATE, None)
                self.engine_menu.set(MY_VOICES)
                self._load_voices(force=True)
                self._status(f"Voz '{voice_name}' clonada! Está em '{MY_VOICES}'.", OK)
                dlg.destroy()

            def fail(e: Exception) -> None:
                status.configure(text=_short(str(e), 160), text_color=ERR)
                btn.configure(state="normal", text="Clonar")

            self.background(lambda: service.clone_voice(path, voice_name, log=progress), done, fail)

        btn.configure(command=go)
        btn.pack(pady=10)
        status.pack()

    # ------------------------------------------------------------ fila

    def _on_generate(self) -> None:
        if not self.photo:
            return self._status("Selecione a foto do avatar.", ERR)
        if not auth.is_connected():
            return self._status("Conecte no HeyGen antes (botão Conectar HeyGen).", ERR)
        common = {
            "photo": self.photo,
            "aspect": self.aspect,
            "resolution": self.resolution,
            "expressiveness": self.expressiveness,
            "motion_prompt": self.motion_entry.get().strip() or None,
            "out_dir": self.out_dir,
        }
        if self.mode == "tts":
            script = self.script_box.get("1.0", "end").strip()
            if not script:
                return self._status("Escreva o texto que o avatar vai falar.", ERR)
            if not self.voice:
                return self._status("Escolha uma voz (botão 'Escolher voz…').", ERR)
            jobs = [VideoJob(**common, script=script, voice_id=self.voice.id, voice_name=self.voice.name)]
        else:
            if not self.audios:
                return self._status("Selecione o áudio (ou use o modo Gerar voz).", ERR)
            cut = bool(self.cut_var.get())
            if cut and not media.has_ffmpeg():
                return self._status("Cortar silêncios precisa do ffmpeg instalado.", ERR)
            jobs = [VideoJob(**common, audio=a, cut_silence=cut, silence_level=self.silence_level) for a in self.audios]
            self.audios = []
            self.audio_value.configure(text="Nenhum áudio", text_color=MUTED)
        for job in jobs:
            self._enqueue(job)
        self._status(f"{len(jobs)} vídeo(s) adicionado(s) à fila.", OK)

    def _enqueue(self, job: VideoJob) -> None:
        if self.empty_lbl is not None:
            self.empty_lbl.destroy()
            self.empty_lbl = None
        self._job_seq += 1
        self.jobs[self._job_seq] = JobCard(self.queue_box, self._job_seq, job)
        self._work.put(self._job_seq)
        self._update_count()

    def _job_worker(self) -> None:
        """Thread única: processa os vídeos em sequência."""
        while True:
            jid = self._work.get()
            job_card = self.jobs[jid]
            self.on_ui(job_card.progress, "Iniciando...")
            try:
                out = service.generate_video(job_card.job, log=lambda m, c=job_card: self.on_ui(c.progress, m))
            except Exception as e:  # noqa: BLE001 - mostrado na fila
                self.on_ui(job_card.fail, str(e) or type(e).__name__)
            else:
                self.on_ui(job_card.done, out)
            self.on_ui(self._update_count)

    def _update_count(self) -> None:
        self.count_lbl.configure(text=f"{self._pending()} na fila/processando")

    def _on_close(self) -> None:
        pending = self._pending()
        if pending and not messagebox.askyesno(
            "Sair?",
            f"Há {pending} vídeo(s) na fila ou em processamento.\n"
            "Se sair agora eles param (o que já foi enviado ao HeyGen continua na sua conta).\n\n"
            "Sair mesmo assim?",
            parent=self,
        ):
            return
        self.after_cancel(self._pump_job)
        self.destroy()


def run() -> None:
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("dark-blue")
    App().mainloop()
