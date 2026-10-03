"""Testes offline (não acessam o HeyGen). Rodar: uv run python tests/smoke_test.py"""
from __future__ import annotations

import asyncio
import contextlib
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
TMP = Path(tempfile.mkdtemp(prefix="avatarize_test_"))
os.environ["AVATARIZE_DIR"] = str(TMP / "data")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from avatarize import auth, config, heygen, media, net, service  # noqa: E402
from avatarize.secure_store import SecureFile  # noqa: E402
from mcp.shared.auth import OAuthToken  # noqa: E402

passed = 0


def check(cond: bool, label: str) -> None:
    global passed
    if not cond:
        raise AssertionError(label)
    passed += 1
    print(f"  ok  {label}")


def raises(exc: type[BaseException], fn, label: str) -> None:
    try:
        fn()
    except exc:
        check(True, label)
    else:
        raise AssertionError(f"{label}: não levantou {exc.__name__}")


print("secure_store / auth")
f = SecureFile(TMP / "x.bin")
f.set("tokens", {"access_token": "segredo-123"})
check(f.load() == {"tokens": {"access_token": "segredo-123"}}, "ida e volta do arquivo criptografado")
check(b"segredo-123" not in (TMP / "x.bin").read_bytes(), "token não aparece em texto puro no disco")
(TMP / "x.bin").write_bytes(b"lixo")
check(f.load() == {}, "arquivo corrompido vira 'sem login'")

check(not auth.is_connected(), "começa desconectado")
store = auth.SessionStorage()
asyncio.run(store.set_tokens(OAuthToken(access_token="abc", token_type="Bearer", refresh_token="r")))
check(auth.is_connected(), "conectado depois de salvar token")
check(asyncio.run(store.get_tokens()).access_token == "abc", "token lido de volta")
auth.logout()
check(not auth.is_connected(), "logout apaga a sessão")


def hit(path: str) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{config.CALLBACK_PORT}{path}", timeout=5) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, ""


print("retorno do OAuth (127.0.0.1)")
rx = auth.LoopbackReceiver()
rx.start()
check(hit("/favicon.ico")[0] == 404, "ignora caminhos que não são /callback")
threading.Timer(0.2, lambda: hit("/callback?code=C0D3&state=ST&iss=https%3A%2F%2Fauth")).start()
params = rx.wait(timeout=5)
check(params == {"code": "C0D3", "state": "ST", "iss": "https://auth"}, "recebe code/state/iss")
rx = auth.LoopbackReceiver()
rx.start()
result: dict = {}
threading.Timer(0.2, lambda: result.update(page=hit("/callback?error=%3Cscript%3Ealert(1)%3C%2Fscript%3E")[1])).start()
rx.wait(timeout=5)
check("<script>" not in result["page"] and "&lt;script&gt;" in result["page"], "erro do login é escapado (sem XSS)")
rx = auth.LoopbackReceiver()
raises(RuntimeError, lambda: rx.wait(timeout=0.2), "timeout do login gera erro claro")

print("respostas das tools")
R = SimpleNamespace
text = lambda t: [R(text=t)]  # noqa: E731
raises(heygen.HeyGenError, lambda: heygen.payload(R(isError=True, content=text("quota"))), "isError vira HeyGenError")
check(heygen.payload(R(isError=False, structuredContent={"data": {"video_id": "v1"}}, content=[]))
      == {"video_id": "v1"}, "structuredContent + desembrulha 'data'")
check(heygen.payload(R(structuredContent=None, content=text('{"a": 1}'))) == {"a": 1}, "JSON no texto")
check(heygen.payload(R(structuredContent=None, content=text("oi"))) == {"_text": "oi"}, "texto que não é JSON")
check(heygen.payload(R(structuredContent=None, content=text("[1,2]"))) == {"items": [1, 2]}, "lista vira items")
raises(heygen.HeyGenError, lambda: heygen.payload(R(structuredContent={"error_code": "x", "message": "m"}, content=[])),
       "error_code vira HeyGenError")
doc = {"id": "top", "videoId": "camel", "nested": {"video_id": "deep"}}
check(heygen.find(doc, "video_id", "id") == "camel", "find aceita camelCase e respeita a prioridade")
check(heygen.find({"a": [{"b": {"upload_url": "u"}}]}, "upload_url") == "u", "find desce em listas")
check(heygen.find({"x": ""}, "x") is None, "find ignora valores vazios")

print("net")
raises(net.InsecureURLError, lambda: net.put_file("http://x/y", TMP / "x.bin", {}), "upload recusa http://")
raises(net.InsecureURLError, lambda: net.download("file:///c:/windows/win.ini", TMP / "a"), "download recusa file://")

print("mídia")
from PIL import Image  # noqa: E402

work = TMP / "work"
work.mkdir()
Image.new("RGB", (64, 64), "red").save(TMP / "foto.webp")
Image.new("RGB", (64, 64), "red").save(TMP / "foto.png")
Image.new("RGB", (64, 64), "red").save(TMP / "foto_png_disfarcada.jpg", format="PNG")
check(media.sniff(TMP / "foto.webp") == "webp", "detecta webp")
check(media.prepare_image(TMP / "foto.png", work, print)[1] == "image/png", "PNG passa direto")
check(media.prepare_image(TMP / "foto_png_disfarcada.jpg", work, print)[1] == "image/png",
      "usa os bytes, não a extensão")
p, mime = media.prepare_image(TMP / "foto.webp", work, print)
check(mime == "image/jpeg" and media.sniff(p) == "jpeg", "webp convertido para JPG")

ff = shutil.which("ffmpeg")
if ff:
    def make(name: str, filt: str) -> Path:
        out = TMP / name
        subprocess.run([ff, "-y", "-f", "lavfi", "-i", filt, str(out)], capture_output=True, check=True)
        return out

    wav = make("fala.wav", "sine=frequency=440:duration=2")
    check(media.prepare_audio(wav, work, print) == (wav, "audio/wav"), "WAV passa direto")
    m4a = make("fala.m4a", "sine=frequency=440:duration=2")
    p, mime = media.prepare_audio(m4a, work, print)
    check(mime == "audio/mpeg" and media.sniff(p) == "mp3", "M4A convertido para MP3")
    mp3 = make("fala.mp3", "sine=frequency=440:duration=2")
    frames = mp3.read_bytes()[media.id3_size(mp3):]
    big = 20000
    tag = b"ID3\x03\x00\x00" + bytes([(big >> 21) & 0x7F, (big >> 14) & 0x7F, (big >> 7) & 0x7F, big & 0x7F])
    fat = TMP / "fala_gorda.mp3"
    fat.write_bytes(tag + b"\x00" * big + frames)
    p, mime = media.prepare_audio(fat, work, print)
    check(mime == "audio/mpeg" and p.read_bytes() == frames, "MP3 com metadados enormes é limpo")
    gaps = make("pausas.wav", "aevalsrc=if(between(mod(t\\,3)\\,1\\,3)\\,0\\,sin(2*PI*440*t)):d=9")
    out = media.remove_silences(gaps, work, "Médio", print)
    before, after = media.duration(gaps), media.duration(out)
    check(after is not None and after < before - 3, f"corte de silêncio encurta o áudio ({before:.1f}s → {after:.1f}s)")
else:
    print("  (ffmpeg não encontrado — testes de áudio pulados)")

print("fluxo completo com HeyGen simulado")
calls: list[tuple[str, dict]] = []
statuses = iter(["pending", "processing", "completed"])


class FakeClient:
    async def call_tool(self, name: str, args: dict):
        calls.append((name, args))
        replies = {
            "create_asset_upload": lambda: {"data": {"asset_id": f"asset-{len(calls)}", "upload_url": "https://s3/put",
                                                     "upload_headers": {"Content-Type": args["contentType"]}}},
            "complete_asset_upload": lambda: {"data": {"url": f"https://cdn/{args['assetId']}"}},
            "create_video_from_image": lambda: {"data": {"video_id": "vid42"}},
            "list_voices": lambda: {"data": {"voices": [{"voice_id": "v1", "name": "Ana", "gender": "female"}]}},
            "get_current_user": lambda: {"data": {"email": "eu@x.com", "first_name": "Eu", "plan": {"name": "Pro"}}},
        }
        if name == "get_video":
            st = next(statuses)
            reply = {"status": st, "video_url": "https://cdn/v.mp4" if st == "completed" else None}
        else:
            reply = replies[name]()
        return R(isError=False, structuredContent=reply, content=[])


@contextlib.asynccontextmanager
async def fake_session(*_a, **_k):
    yield FakeClient()


uploads: list[str] = []
service.open_session = fake_session
service.net.put_file = lambda url, path, headers: uploads.append(path.name) or 200
service.net.download = lambda url, dest: (dest.parent.mkdir(parents=True, exist_ok=True), dest.write_bytes(b"mp4"), dest)[2]
_real_sleep = asyncio.sleep
service.asyncio.sleep = lambda *_a: _real_sleep(0)

job = service.VideoJob(photo=TMP / "foto.webp", audio=(TMP / "fala.m4a") if ff else (TMP / "fala.wav"),
                       aspect="16:9", resolution="720p", expressiveness="high", motion_prompt="smile",
                       out_dir=TMP / "videos")
if not ff:
    (TMP / "fala.wav").write_bytes(b"RIFF\x00\x00\x00\x00WAVEfmt ")
out = service.generate_video(job, log=lambda m: None)
body = next(a for n, a in calls if n == "create_video_from_image")
check(out.exists() and out.name.endswith("_vid42.mp4"), "MP4 salvo na pasta escolhida")
check(body["image"] == {"type": "url", "url": "https://cdn/asset-1"}, "foto enviada e referenciada pela URL")
check(body["audioUrl"].startswith("https://cdn/asset-") and "audioAssetId" not in body, "áudio enviado e referenciado")
check((body["aspectRatio"], body["resolution"], body["expressiveness"], body["motionPrompt"])
      == ("16:9", "720p", "high", "smile"), "opções do vídeo chegam no payload")
check([n for n, _ in calls].count("get_video") == 3, "espera o vídeo até 'completed'")
check(all(Path(u).suffix in (".jpg", ".mp3", ".wav") for u in uploads), "só sobe JPG/PNG e MP3/WAV")

calls.clear()
statuses = iter(["completed"])
tts = service.VideoJob(photo=TMP / "foto.png", script="Olá!", voice_id="v1", voice_name="Ana",
                       voice_speed=1.1, out_dir=TMP / "videos")
service.generate_video(tts)
body = next(a for n, a in calls if n == "create_video_from_image")
check(body["script"] == "Olá!" and body["voiceId"] == "v1" and body["voiceSettings"] == {"speed": 1.1},
      "modo texto + voz monta o payload certo")
check(not any(n == "create_asset_upload" and a["contentType"].startswith("audio") for n, a in calls),
      "modo texto não sobe áudio")
check(service.list_voices(engine="elevenlabs")[0].name == "Ana", "list_voices")
check(service.whoami(interactive=False)["plan"] == "Pro", "whoami lê email/plano")
raises(ValueError, lambda: service.generate_video(service.VideoJob(photo=TMP / "foto.png")), "job sem áudio nem texto")

print("ponte da interface (sem janela)")
import time as _time  # noqa: E402

from avatarize import app as app_mod  # noqa: E402

ponte = app_mod.Ponte()
check(ponte.generate({"modo": "audio"}) == {"erro": "Conecte sua conta HeyGen primeiro."}, "gerar sem login é recusado")
asyncio.run(auth.SessionStorage().set_tokens(OAuthToken(access_token="t", token_type="Bearer")))
check("erro" in ponte.generate({"modo": "audio"}), "gerar sem foto é recusado")
foto = ponte._photo_info(TMP / "foto.png")
check(foto["thumb"].startswith("data:image/jpeg;base64,") and "64×64" in foto["info"], "foto ganha miniatura e tamanho")
check("erro" in ponte.generate({"modo": "audio", "audios": []}), "gerar sem áudio é recusado")
check("erro" in ponte.generate({"modo": "texto", "texto": "oi"}), "modo texto sem voz é recusado")

feitos: list = []
falhar = {"vez": True}


def fake_generate(spec, log=None, on_step=None):
    for etapa in (service.STEPS_TEXT if spec.script else service.STEPS_AUDIO):
        on_step(etapa)
    if spec.audio and spec.audio.name == "b.wav" and falhar["vez"]:
        falhar["vez"] = False
        raise RuntimeError("créditos insuficientes")
    feitos.append(spec)
    out = TMP / "videos" / f"{len(feitos)}.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(b"mp4")
    return out


app_mod.service.generate_video = fake_generate
(TMP / "a.wav").write_bytes(b"RIFF\x00\x00\x00\x00WAVEfmt ")
(TMP / "b.wav").write_bytes(b"RIFF\x00\x00\x00\x00WAVEfmt ")
ids = [ponte._audio_info(TMP / n)["id"] for n in ("a.wav", "b.wav")]
r = ponte.generate({"modo": "audio", "audios": ids, "formato": "16:9", "res": "4k", "expr": "high", "movimento": " smile "})
check(len(r["jobs"]) == 2 and r["jobs"][0]["state"] == "queued", "um job por áudio, entra na fila")
check(r["jobs"][0]["resolution"] == "1080p" and r["jobs"][0]["aspect"] == "16:9", "valores inválidos viram o padrão")


def esperar(cond, segundos=5.0):
    fim = _time.time() + segundos
    while _time.time() < fim and not cond():
        _time.sleep(0.05)
    return cond()


j1, j2 = (j["id"] for j in r["jobs"])
check(esperar(lambda: ponte._jobs[j2]["state"] in ("done", "error")), "fila processa em sequência")
check(ponte._jobs[j1]["state"] == "done" and ponte._jobs[j1]["step"] == "baixar", "job pronto passou por todas as etapas")
check(ponte._jobs[j2]["state"] == "error" and "créditos" in ponte._jobs[j2]["error"], "erro aparece no job")
check(feitos[0].motion_prompt == "smile" and feitos[0].expressiveness == "high", "opções chegam no motor")
check(ponte.retry(j2)["state"] == "queued", "tentar de novo recoloca na fila")
check(esperar(lambda: ponte._jobs[j2]["state"] == "done"), "segunda tentativa funciona")
check(ponte.remove(j1) and j1 not in ponte._jobs, "remover da lista")
ponte.logout()
check(not auth.is_connected(), "sair apaga a sessão")

events: list = []
ponte._emit = lambda tipo, **d: events.append((tipo, d))
(TMP / "x.bin").write_bytes(b"nada")
ponte._on_drop({"dataTransfer": {"files": [
    {"name": "foto.png", "pywebviewFullPath": str(TMP / "foto.png")},
    {"name": "a.wav", "pywebviewFullPath": str(TMP / "a.wav")},
    {"name": "x.bin", "pywebviewFullPath": str(TMP / "x.bin")},
]}})
tipo, d = events[-1]
check(tipo == "drop" and d["foto"]["name"] == "foto.png" and len(d["audios"]) == 1 and d["outros"] == 1,
      "arrastar separa foto, áudio e outros")

shutil.rmtree(TMP, ignore_errors=True)
print(f"\n{passed} verificações passaram.")
