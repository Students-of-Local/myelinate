#!/usr/bin/env python3
"""Make the narration audio for a Myelinate video lesson: one clip per sentence, one voice for the whole lesson.

    python3 scripts/video_voice.py lesson.json                   # pick the best voice engine here, make every clip
    python3 scripts/video_voice.py lesson.json --sample 30       # only the first 30 s, plus audio/sample.mp3
    python3 scripts/video_voice.py lesson.json --engine browser  # force one engine
    python3 scripts/video_voice.py lesson.json --engine none     # no audio: the player uses the browser's own voice

Options:
    --out DIR        where clips go (default: an "audio" folder next to the lesson)
    --engine NAME    auto (default), cmd, endpoint, kokoro, kokoro-onnx, piper, browser or none
    --cmd TEMPLATE   a text-to-speech command with {text_file} (UTF-8 text in) and {out} (WAV out),
                     and optionally {voice}. Also read from MYELINATE_TTS_CMD. For example:
                       ~/.local/bin/my-tts --text-file {text_file} --output {out} --speaker {voice}
    --endpoint URL   an OpenAI-compatible server: POST URL/v1/audio/speech. Also MYELINATE_TTS_URL.
    --voice NAME     a stock voice name of the engine (default af_heart for Kokoro). Never a real person's voice.
    --model NAME     the model name sent to an endpoint and named in the credits (or MYELINATE_TTS_MODEL)
    --speed N        speaking speed (1 = the engine's normal). Kokoro speaks fast, so its engines default to
                     the lesson's "wpm"; other engines default to 1. {speed} works in a --cmd template.
    --sample SECONDS make only the first lines (about SECONDS long) and join them into OUT/sample.mp3
    --wait MINUTES   if a command says the GPU is in use, retry every 60 s for up to MINUTES
    --no-check       skip scripts/voice_check.py at the end
    --asr NAME       the speech-to-text engine voice_check.py uses (default auto; none skips the round trip)

Engines, best first (auto takes the first one that works and says why it skipped the others):
    cmd, endpoint, kokoro (Python package), kokoro-onnx, piper, browser (Kokoro-82M in headless Chromium
    through kokoro-js; needs Python playwright, or Node with playwright or playwright-core on NODE_PATH), none.

The lesson may carry "pronounce": {"heterozygote": "hetero zygote"}. It changes only what the engine reads, never the
captions or the clip names. Each clip is trimmed, leveled to -19 LUFS and saved as OUT/<clip name>.mp3,
then the lesson gets "audio": {"clips": {...}, "voice": {...}} with a credit line for the AI voice.
OUT/voice.json remembers what was made, so a rerun only remakes clips whose text, voice or engine changed.

Exit codes: 0 done; 1 voice_check found problems; 2 bad input; 3 no engine produced audio when one was
forced, or the engine stopped partway. This script never installs anything.
"""
import argparse
import base64
import hashlib
import importlib.util
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import video_check as vc  # noqa: E402

ENGINES = ('cmd', 'endpoint', 'kokoro', 'kokoro-onnx', 'piper', 'browser')
KOKORO_JS = '1.2.1'  # published 2025-05-03 on npm
KOKORO_JS_URL = f'https://cdn.jsdelivr.net/npm/kokoro-js@{KOKORO_JS}/+esm'
KOKORO_MODEL = 'onnx-community/Kokoro-82M-v1.0-ONNX'
KOKORO_NAME = 'Kokoro-82M'
DEFAULT_VOICE = 'af_heart'
PROFILE = Path.home() / '.cache' / 'myelinate-voice'
PAGE_URL = 'https://myelinate-voice.localhost/'
GAP = vc.BEAT_GAP  # silence between sentences in the player and in sample.mp3
EDGE = 0.1  # seconds of silence kept at each end of a clip
TARGET_LUFS, TARGET_TP, TARGET_LRA = -19.0, -1.5, 11
RATE = 24000
POST = {'edge': EDGE, 'lufs': TARGET_LUFS, 'tp': TARGET_TP, 'lra': TARGET_LRA, 'limit': -3.0, 'rate': RATE,
        'channels': 1, 'bitrate': '128k'}
# Kokoro's stock voices speak about 205 words a minute at speed 1 (af_heart over the sky example's first
# 7 lines, measured on Parish1 2026-11-22). The Kokoro engines slow to the lesson's "wpm" unless --speed is given.
KOKORO_WPM = 205
RETRY_SECONDS = 60
GPU_BUSY = re.compile(r'gpu is in use', re.I)
NOT_INSTALLED = 'This script never installs anything.'


class Skip(Exception):
    """The engine cannot run here. Auto mode moves to the next one."""


class Busy(Skip):
    """The engine refused because the GPU is in use."""


class Broke(Exception):
    """The engine worked, then failed partway through the lesson."""


def say(msg=''):
    print(msg, flush=True)


# ---------- What to say ----------

def plan_lines(lesson_path):
    """[(key, caption text)] for every line the player speaks, from video_check.py --audio-plan, in order, once each."""
    r = subprocess.run([sys.executable, str(HERE / 'video_check.py'), str(lesson_path), '--audio-plan'],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise ValueError((r.stdout + r.stderr).strip() or 'video_check.py --audio-plan failed')
    out, seen = [], set()
    for item in json.loads(r.stdout):
        text = item.get('text') if isinstance(item, dict) else None
        if not isinstance(text, str) or not text.strip():
            continue
        key = vc.fnv1a(text)
        if key not in seen:
            seen.add(key)
            out.append((key, text))
    return out


def apply_pronounce(text, pronounce):
    """Swap each "pronounce" key for its respelling: whole words, any case, hyphenated keys too. Captions keep the real word."""
    if not isinstance(pronounce, dict):
        return text
    pairs = [(' '.join(str(k).split()), v.strip()) for k, v in pronounce.items()
             if str(k).strip() and isinstance(v, str) and v.strip()]
    if not pairs:
        return text
    pairs.sort(key=lambda kv: -len(kv[0]))
    table = {k.lower(): v for k, v in pairs}
    alts = '|'.join(r'\s+'.join(re.escape(part) for part in k.split(' ')) for k, _ in pairs)
    rx = re.compile(r'(?<!\w)(?:' + alts + r')(?!\w)', re.I)
    return rx.sub(lambda m: table.get(' '.join(m.group(0).lower().split()), m.group(0)), text)


def tts_hash(engine, voice, settings, tts_text):
    blob = json.dumps({'engine': engine, 'voice': voice, 'settings': settings, 'text': tts_text},
                      sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode('utf-8')).hexdigest()


def sample_lines(lines, seconds, wpm):
    """The first lines whose estimated length adds up to about `seconds`."""
    picked, total = [], 0.0
    for key, text in lines:
        if picked and total >= seconds:
            break
        picked.append((key, text))
        total += vc.spoken_words(text) * 60.0 / wpm + GAP
    return picked


# ---------- Cache ----------

def load_cache(out):
    try:
        data = json.loads((out / 'voice.json').read_text())
        return data if isinstance(data, dict) and isinstance(data.get('clips'), dict) else None
    except (OSError, ValueError):
        return None


def cache_hit(cache, engine, key, digest, out):
    if not cache or cache.get('engine') != engine.name or cache.get('voice') != engine.voice:
        return False
    entry = cache['clips'].get(key)
    return isinstance(entry, dict) and entry.get('tts_sha256') == digest and (out / str(entry.get('file', ''))).is_file()


def save_cache(out, engine, clips, extra=None):
    data = {'engine': engine.name, 'voice': engine.voice, 'settings': engine.full_settings(), 'clips': clips}
    if extra:
        data.update(extra)
    (out / 'voice.json').write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n')


# ---------- Audio processing ----------

def ffmpeg(*args, check=True):
    r = subprocess.run(['ffmpeg', '-hide_banner', '-nostdin', '-y', *args], capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError('ffmpeg failed: ' + r.stderr.strip()[-600:])
    return r


def encoder():
    """('libmp3lame', '.mp3') when ffmpeg can make MP3, else ('aac', '.m4a')."""
    r = subprocess.run(['ffmpeg', '-hide_banner', '-encoders'], capture_output=True, text=True)
    return ('libmp3lame', '.mp3') if 'libmp3lame' in r.stdout else ('aac', '.m4a')


def trim_filter():
    one = f'silenceremove=start_periods=1:start_threshold=-50dB:start_silence={EDGE}'
    return f'aformat=channel_layouts=mono,{one},areverse,{one},areverse'


def finish_clip(raw, dest, codec):
    """Trim the silence at each end to EDGE s, level to TARGET_LUFS (two-pass loudnorm), 24 kHz mono, encode."""
    measure = ffmpeg('-i', str(raw), '-af', trim_filter() + f',loudnorm=I={TARGET_LUFS}:TP={TARGET_TP}:LRA={TARGET_LRA}:print_format=json',
                     '-f', 'null', '-').stderr
    found = re.findall(r'\{[^{}]*"input_i"[^{}]*\}', measure, re.S)
    chain = trim_filter()
    if found:
        m = json.loads(found[-1])
        if m.get('input_i') not in ('-inf', None) and float(m['input_i']) > -70:
            chain += (f',loudnorm=I={TARGET_LUFS}:TP={TARGET_TP}:LRA={TARGET_LRA}:measured_I={m["input_i"]}'
                      f':measured_TP={m["input_tp"]}:measured_LRA={m["input_lra"]}:measured_thresh={m["input_thresh"]}'
                      f':offset={m["target_offset"]}:linear=true')
    chain += f',aresample={RATE}'
    wav = dest.with_suffix('.level.wav')
    ffmpeg('-i', str(raw), '-af', chain, '-ac', '1', '-ar', str(RATE), '-c:a', 'pcm_f32le', str(wav))
    # Speech peaks often stop loudnorm short of the target (it keeps the true peak under TP).
    # A gain step into a peak limiter lands it; a few rounds settle what the limiter takes back.
    import voice_check
    limit = 10 ** (POST['limit'] / 20)
    for _ in range(4):
        level = voice_check.loudness(wav)
        if level['i'] is None or level['i'] <= -70:
            break
        if abs(level['i'] - TARGET_LUFS) <= 0.3 and (level['tp'] is None or level['tp'] <= TARGET_TP - 0.5):
            break
        step = wav.with_suffix('.step.wav')
        ffmpeg('-i', str(wav), '-af', f'volume={TARGET_LUFS - level["i"]:.2f}dB,alimiter=limit={limit:.4f}:attack=5:release=50:level=0',
               '-ac', '1', '-ar', str(RATE), '-c:a', 'pcm_f32le', str(step))
        step.replace(wav)
    ffmpeg('-i', str(wav), '-ac', '1', '-ar', str(RATE), '-c:a', codec, '-b:a', POST['bitrate'], str(dest))
    wav.unlink(missing_ok=True)


def join_sample(files, dest, codec):
    """Join clips with GAP seconds of silence between them, like the player."""
    args, parts = [], []
    for i, f in enumerate(files):
        args += ['-i', str(f)]
    n = len(files)
    for i in range(n):
        parts.append(f'[{i}:a]aformat=sample_rates={RATE}:channel_layouts=mono[a{i}]')
    pieces = []
    for i in range(n):
        pieces.append(f'[a{i}]')
        if i < n - 1:
            parts.append(f'anullsrc=r={RATE}:cl=mono,atrim=duration={GAP}[g{i}]')
            pieces.append(f'[g{i}]')
    graph = ';'.join(parts) + ';' + ''.join(pieces) + f'concat=n={len(pieces)}:v=0:a=1[out]'
    ffmpeg(*args, '-filter_complex', graph, '-map', '[out]', '-ac', '1', '-ar', str(RATE),
           '-c:a', codec, '-b:a', POST['bitrate'], str(dest))


# ---------- Engines ----------

class Engine:
    name = ''
    model = ''

    def __init__(self, args):
        self.args = args
        self.voice = args.voice or DEFAULT_VOICE
        self.speed = args.speed

    def settings(self):
        return {}

    def full_settings(self):
        return dict(self.settings(), post=POST)

    def check(self):
        """Raise Skip with a plain reason if this engine cannot run here. Must be cheap."""

    def start(self):
        pass

    def synth(self, text, wav):
        raise NotImplementedError

    def close(self):
        pass

    def disclose(self):
        return f'Narration is an AI voice: {self.model} ({self.voice}).'


class CmdEngine(Engine):
    name = 'cmd'

    def __init__(self, args):
        super().__init__(args)
        self.template = args.cmd or os.environ.get('MYELINATE_TTS_CMD', '')
        self.voice = args.voice or 'default'
        prog = shlex.split(self.template)[0] if self.template.strip() else 'command'
        self.model = args.model or os.environ.get('MYELINATE_TTS_MODEL') or Path(prog).name

    def settings(self):
        return {'cmd': self.template, 'speed': self.speed}

    def check(self):
        if not self.template.strip():
            raise Skip('no --cmd and no MYELINATE_TTS_CMD')
        if '{text_file}' not in self.template or '{out}' not in self.template:
            raise Skip('the command needs both {text_file} and {out} in it')

    def synth(self, text, wav):
        tdir = wav.parent
        text_file = tdir / (wav.stem + '.txt')
        text_file.write_text(text + '\n', encoding='utf-8')
        waited = 0
        while True:
            # Some TTS tools refuse to overwrite: every attempt gets a new output name.
            target = tdir / f'{wav.stem}-{int(time.time() * 1000)}.wav'
            cmd = (self.template.replace('{text_file}', shlex.quote(str(text_file)))
                   .replace('{out}', shlex.quote(str(target))).replace('{voice}', shlex.quote(self.voice))
                   .replace('{speed}', str(self.speed or 1)))
            r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            said = (r.stdout + '\n' + r.stderr).strip()
            if r.returncode == 0 and target.is_file() and target.stat().st_size > 44:
                target.replace(wav)
                return
            if GPU_BUSY.search(said):
                if waited < (self.args.wait or 0):
                    waited += 1
                    say(f'  The command says the GPU is in use. Trying again in {RETRY_SECONDS} s ({waited} of {self.args.wait}).')
                    time.sleep(RETRY_SECONDS)
                    continue
                raise Busy('the command refused, saying: ' + said[-800:])
            last = said.splitlines()[-1] if said else f'exit {r.returncode}, no output file'
            raise Skip(f'the command failed: {last}')


class EndpointEngine(Engine):
    name = 'endpoint'

    def __init__(self, args):
        super().__init__(args)
        self.url = (args.endpoint or os.environ.get('MYELINATE_TTS_URL', '')).rstrip('/')
        self.model = args.model or os.environ.get('MYELINATE_TTS_MODEL') or 'kokoro'

    def settings(self):
        return {'url': self.url, 'model': self.model, 'speed': self.speed}

    def check(self):
        if not self.url:
            raise Skip('no --endpoint and no MYELINATE_TTS_URL')

    def synth(self, text, wav):
        url = self.url if self.url.endswith('/audio/speech') else self.url + '/v1/audio/speech'
        req_body = {'model': self.model, 'input': text, 'voice': self.voice, 'response_format': 'wav'}
        if self.speed:
            req_body['speed'] = self.speed
        body = json.dumps(req_body).encode()
        req = urllib.request.Request(url, data=body, headers={'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                data = resp.read()
        except (urllib.error.URLError, OSError) as exc:
            raise Skip(f'{url} did not answer: {exc}')
        if len(data) < 44:
            raise Skip(f'{url} sent no audio')
        wav.write_bytes(data)


def write_wav(path, samples, rate):
    """Write float samples (-1 to 1) as 16-bit mono WAV."""
    import wave
    import array
    pcm = array.array('h', (max(-32768, min(32767, int(round(float(s) * 32767)))) for s in samples))
    with wave.open(str(path), 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())


def kokoro_speed(args):
    """--speed, or the speed that brings Kokoro from about KOKORO_WPM to the lesson's words a minute."""
    if args.speed:
        return args.speed
    return round(min(1.2, max(0.5, (getattr(args, 'lesson_wpm', None) or 145) / KOKORO_WPM)), 2)


class KokoroEngine(Engine):
    name = 'kokoro'
    model = KOKORO_NAME

    def __init__(self, args):
        super().__init__(args)
        self.speed = kokoro_speed(args)

    def settings(self):
        return {'package': 'kokoro', 'lang': 'a', 'rate': 24000, 'speed': self.speed}

    def check(self):
        if importlib.util.find_spec('kokoro') is None:
            raise Skip('the Python package kokoro is not installed')

    def start(self):
        try:
            from kokoro import KPipeline
            self.pipe = KPipeline(lang_code='a')
        except Exception as exc:
            raise Skip(f'kokoro would not load: {exc}')

    def synth(self, text, wav):
        chunks = []
        for item in self.pipe(text, voice=self.voice, speed=self.speed):
            audio = item[-1] if isinstance(item, tuple) else getattr(item, 'audio', None)
            if audio is not None:
                chunks.extend(audio.tolist() if hasattr(audio, 'tolist') else list(audio))
        if not chunks:
            raise Skip('kokoro made no audio')
        write_wav(wav, chunks, 24000)


def kokoro_onnx_files():
    dirs = [os.environ.get('KOKORO_ONNX_DIR', ''), '.', str(Path.home() / '.cache' / 'kokoro-onnx'),
            str(Path.home() / '.local' / 'share' / 'kokoro-onnx'), str(Path.home() / '.cache' / 'kokoro'),
            str(Path.home() / 'models' / 'kokoro')]
    for d in dirs:
        if not d or not Path(d).is_dir():
            continue
        models = sorted(Path(d).glob('kokoro*.onnx'))
        voices = sorted(Path(d).glob('voices*.bin')) + sorted(Path(d).glob('voices*.npz'))
        if models and voices:
            return models[0], voices[0]
    return None


class KokoroOnnxEngine(Engine):
    name = 'kokoro-onnx'
    model = KOKORO_NAME

    def __init__(self, args):
        super().__init__(args)
        self.speed = kokoro_speed(args)

    def settings(self):
        files = kokoro_onnx_files()
        return {'package': 'kokoro-onnx', 'model_file': files[0].name if files else '', 'lang': 'en-us', 'speed': self.speed}

    def check(self):
        if importlib.util.find_spec('kokoro_onnx') is None:
            raise Skip('the Python package kokoro_onnx is not installed')
        if not kokoro_onnx_files():
            raise Skip('no kokoro*.onnx and voices*.bin found (set KOKORO_ONNX_DIR)')

    def start(self):
        try:
            from kokoro_onnx import Kokoro
            model, voices = kokoro_onnx_files()
            self.k = Kokoro(str(model), str(voices))
        except Exception as exc:
            raise Skip(f'kokoro-onnx would not load: {exc}')

    def synth(self, text, wav):
        samples, rate = self.k.create(text, voice=self.voice, speed=self.speed, lang='en-us')
        write_wav(wav, samples, rate)


class PiperEngine(Engine):
    name = 'piper'
    model = 'Piper'

    def __init__(self, args):
        super().__init__(args)
        self.file = self.find_voice()
        self.voice = args.voice or (self.file.stem if self.file else 'default')

    def find_voice(self):
        env = os.environ.get('PIPER_VOICE', '')
        if env and Path(env).is_file():
            return Path(env)
        base = Path.home() / '.local' / 'share' / 'piper'
        found = sorted(base.rglob('*.onnx')) if base.is_dir() else []
        if self.args.voice:
            found = [f for f in found if f.stem == self.args.voice]
        return found[0] if found else None

    def settings(self):
        return {'voice_file': self.file.name if self.file else '', 'speed': self.speed}

    def check(self):
        if not shutil.which('piper'):
            raise Skip('no piper command on PATH')
        if not self.file:
            raise Skip('no piper voice .onnx in PIPER_VOICE or ~/.local/share/piper')

    def synth(self, text, wav):
        extra = ['--length_scale', f'{1 / self.speed:.3f}'] if self.speed else []
        r = subprocess.run(['piper', '--model', str(self.file), '--output_file', str(wav), *extra], input=text,
                           capture_output=True, text=True)
        if r.returncode != 0 or not wav.is_file():
            raise Skip('piper failed: ' + (r.stderr.strip().splitlines() or ['no output'])[-1])


# The page that runs Kokoro. Served by request interception at a fixed https origin, so the
# model weights land in the persistent profile's cache and download only once.
VOICE_PAGE = """<!doctype html><meta charset="utf-8"><title>Myelinate voice</title>
<script type="module">
window.__voiceInit = async (url, model, dtype, voice, device) => {
  const {KokoroTTS} = await import(url);
  if (device === 'webgpu' && !(navigator.gpu && await navigator.gpu.requestAdapter().catch(() => null)))
    throw new Error('WebGPU is not available in this browser');
  const tts = await KokoroTTS.from_pretrained(model, {dtype, device});
  window.__tts = tts;
  const voices = Object.keys(tts.voices || {});
  if (voices.length && !voices.includes(voice)) throw new Error('Unknown voice ' + voice + '. Stock voices: ' + voices.join(', '));
  return {device, voices: voices.length};
};
window.__voiceSay = async (text, voice, speed) => {
  const audio = await window.__tts.generate(text, {voice, speed});
  const bytes = new Uint8Array(audio.toWav());
  let s = '';
  for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
  return btoa(s);
};
window.__voicePageReady = true;
</script>"""

# Node driver: one JSON request per stdin line, one JSON answer per stdout line.
NODE_DRIVER = r"""
const {chromium} = require(process.env.VV_MODULE);
const a = JSON.parse(process.env.VV_ARGS);
const readline = require('readline');
const send = o => process.stdout.write(JSON.stringify(o) + '\n');
(async () => {
  let ctx;
  try { ctx = await chromium.launchPersistentContext(a.profile, {headless: true, args: ['--enable-unsafe-webgpu']}); }
  catch (e) { send({type: 'error', stage: 'launch', message: String(e && e.message || e)}); process.exit(0); }
  try {
    const page = ctx.pages()[0] || await ctx.newPage();
    await page.route(a.pageUrl, r => r.fulfill({status: 200, contentType: 'text/html', body: a.html}));
    await page.goto(a.pageUrl, {waitUntil: 'load'});
    await page.waitForFunction(() => window.__voicePageReady === true, null, {timeout: 30000});
    const info = await page.evaluate(([u, m, d, v, g]) => window.__voiceInit(u, m, d, v, g), [a.url, a.model, a.dtype, a.voice, a.device]);
    send(Object.assign({type: 'ready'}, info));
    const rl = readline.createInterface({input: process.stdin});
    for await (const line of rl) {
      if (!line.trim()) continue;
      const job = JSON.parse(line);
      try {
        const b64 = await page.evaluate(([t, v, s]) => window.__voiceSay(t, v, s), [job.text, a.voice, a.speed]);
        require('fs').writeFileSync(job.out, Buffer.from(b64, 'base64'));
        send({type: 'done'});
      } catch (e) { send({type: 'error', stage: 'say', message: String(e && e.message || e)}); }
    }
  } catch (e) { send({type: 'error', stage: 'load', message: String(e && e.message || e)}); }
  await ctx.close();
})();
"""


def node_module():
    """'playwright-core' or 'playwright' if Node can load it here (NODE_PATH included), else None."""
    node = shutil.which('node')
    if not node:
        return None
    for mod in ('playwright-core', 'playwright'):
        try:
            r = subprocess.run([node, '-e', f'require.resolve({json.dumps(mod)})'], capture_output=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            return None
        if r.returncode == 0:
            return mod
    return None


def python_playwright():
    try:
        import playwright.sync_api  # noqa: F401
        return True
    except Exception:
        return False


class BrowserEngine(Engine):
    """Kokoro-82M through kokoro-js in headless Chromium.

    Runs on wasm with q8 weights. Measured on Parish1 (2026-11-22): q8 weights on WebGPU made noise that
    Whisper could not read (127% word error rate), and kokoro-js needs fp32 weights on WebGPU. So WebGPU is
    used only when MYELINATE_VOICE_DEVICE=webgpu, and then with fp32 weights (about 330 MB).
    """
    name = 'browser'
    model = KOKORO_NAME

    def __init__(self, args):
        super().__init__(args)
        self.driver = None
        self.device = 'webgpu' if os.environ.get('MYELINATE_VOICE_DEVICE', '').lower() == 'webgpu' else 'wasm'
        self.dtype = 'fp32' if self.device == 'webgpu' else 'q8'
        self.speed = kokoro_speed(args)

    def settings(self):
        return {'kokoro_js': KOKORO_JS, 'model': KOKORO_MODEL, 'dtype': self.dtype, 'device': self.device, 'speed': self.speed}

    def check(self):
        if python_playwright():
            self.driver = ('python', None)
            return
        mod = node_module()
        if mod:
            self.driver = ('node', mod)
            return
        raise Skip('no Playwright driver (Python playwright, or Node with playwright or playwright-core on NODE_PATH)')

    def start(self):
        PROFILE.mkdir(parents=True, exist_ok=True)
        say(f'  Loading {KOKORO_NAME} in headless Chromium (kokoro-js {KOKORO_JS}). The first run downloads about 90 MB.')
        if self.driver[0] == 'python':
            self.start_python()
        else:
            self.start_node()
        say(f'  Kokoro is running on {self.device}.')

    def start_python(self):
        from playwright.sync_api import sync_playwright
        try:
            self.pw = sync_playwright().start()
            self.ctx = self.pw.chromium.launch_persistent_context(str(PROFILE), headless=True, args=['--enable-unsafe-webgpu'])
            page = self.ctx.pages[0] if self.ctx.pages else self.ctx.new_page()
            page.route(PAGE_URL, lambda r: r.fulfill(status=200, content_type='text/html', body=VOICE_PAGE))
            page.goto(PAGE_URL, wait_until='load')
            page.wait_for_function('() => window.__voicePageReady === true', timeout=30000)
            page.set_default_timeout(0)
            info = page.evaluate('([u, m, d, v, g]) => window.__voiceInit(u, m, d, v, g)',
                                 [KOKORO_JS_URL, KOKORO_MODEL, self.dtype, self.voice, self.device])
        except Exception as exc:
            self.close()
            raise Skip(f'the browser voice would not start: {str(exc).splitlines()[0]}')
        self.page = page

    def start_node(self):
        env = dict(os.environ, VV_MODULE=self.driver[1], VV_ARGS=json.dumps({
            'profile': str(PROFILE), 'pageUrl': PAGE_URL, 'html': VOICE_PAGE, 'url': KOKORO_JS_URL,
            'model': KOKORO_MODEL, 'dtype': self.dtype, 'voice': self.voice, 'device': self.device, 'speed': self.speed}))
        self.proc = subprocess.Popen([shutil.which('node'), '-e', NODE_DRIVER], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=env)
        msg = self.read()
        if msg.get('type') != 'ready':
            self.close()
            raise Skip(f'the browser voice would not start ({msg.get("stage", "?")}): {msg.get("message", "")[:300]}')

    def read(self):
        line = self.proc.stdout.readline()
        if not line:
            return {'type': 'error', 'stage': 'driver', 'message': 'the Node driver exited'}
        return json.loads(line)

    def synth(self, text, wav):
        if self.driver[0] == 'python':
            try:
                b64 = self.page.evaluate('([t, v, s]) => window.__voiceSay(t, v, s)', [text, self.voice, self.speed])
            except Exception as exc:
                raise Skip(f'Kokoro failed: {str(exc).splitlines()[0]}')
            wav.write_bytes(base64.b64decode(b64))
            return
        self.proc.stdin.write(json.dumps({'text': text, 'out': str(wav)}) + '\n')
        self.proc.stdin.flush()
        msg = self.read()
        if msg.get('type') != 'done':
            raise Skip(f'Kokoro failed: {msg.get("message", "")[:300]}')

    def close(self):
        if getattr(self, 'proc', None):
            try:
                self.proc.stdin.close()
                self.proc.wait(timeout=30)
            except Exception:
                self.proc.kill()
            self.proc = None
        if getattr(self, 'ctx', None):
            try:
                self.ctx.close()
                self.pw.stop()
            except Exception:
                pass
            self.ctx = None


CLASSES = {'cmd': CmdEngine, 'endpoint': EndpointEngine, 'kokoro': KokoroEngine, 'kokoro-onnx': KokoroOnnxEngine,
           'piper': PiperEngine, 'browser': BrowserEngine}


# ---------- Lesson file ----------

def indent_of(text):
    m = re.search(r'^\{\s*\n( +)"', text)
    return len(m.group(1)) if m else 2


def write_lesson(path, lesson, original_text):
    text = json.dumps(lesson, indent=indent_of(original_text), ensure_ascii=False)
    Path(path).write_text(text + '\n')


def clip_seconds(path):
    r = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=nw=1:nk=1', str(path)],
                       capture_output=True, text=True)
    try:
        return round(float(r.stdout.strip()), 2)
    except ValueError:
        raise Broke(f'Could not read the length of {path.name} with ffprobe. Make the clip again.')


def clip_path(out, name, lesson_dir):
    return os.path.relpath(out / name, lesson_dir).replace(os.sep, '/')


# ---------- Main ----------

def run(engine, lines, todo, out, cache, codec):
    """Make every clip in `todo` with one engine. Returns the voice.json clip table."""
    clips = {}
    if cache and cache.get('engine') == engine.name and cache.get('voice') == engine.voice:
        clips = {k: v for k, v in cache['clips'].items() if isinstance(v, dict)}
    tmp = Path(tempfile.mkdtemp(prefix='.voice-tmp-', dir=out))
    started = False
    try:
        for n, (key, text, tts_text, digest) in enumerate(todo, 1):
            raw = tmp / f'{key}.wav'
            if not started:
                engine.start()
                started = True
            t0 = time.time()
            try:
                engine.synth(tts_text, raw)
            except Skip as exc:
                if n == 1:
                    raise
                save_cache(out, engine, clips)
                raise Broke(f'{engine.name} stopped at clip {n} of {len(todo)}: {exc}. The clips made so far are saved; run the same command again to finish.')
            name = key + codec[1]
            finish_clip(raw, out / name, codec[0])
            clips[key] = {'file': name, 'tts_sha256': digest, 'engine': engine.name, 'voice': engine.voice}
            say(f'  {n}/{len(todo)} {name} ({time.time() - t0:.1f} s): {text[:70]}')
    finally:
        if started:
            engine.close()
        shutil.rmtree(tmp, ignore_errors=True)
    return clips


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('lesson')
    ap.add_argument('--out', help='folder for the clips (default: audio next to the lesson)')
    ap.add_argument('--engine', default='auto', choices=('auto',) + ENGINES + ('none',))
    ap.add_argument('--cmd', help='TTS command with {text_file} and {out}')
    ap.add_argument('--endpoint', help='OpenAI-compatible server address')
    ap.add_argument('--voice', help='stock voice name')
    ap.add_argument('--model', help='model name for an endpoint, and the name used in the credits')
    ap.add_argument('--speed', type=float, help='speaking speed, 1 is the engine default (Kokoro defaults to the lesson pace)')
    ap.add_argument('--sample', type=float, metavar='SECONDS', help='make only the first SECONDS and OUT/sample.mp3')
    ap.add_argument('--wait', type=float, default=0, metavar='MINUTES', help='retry a busy GPU every 60 s for this long')
    ap.add_argument('--no-check', action='store_true', help='skip voice_check.py at the end')
    ap.add_argument('--asr', default='auto', help='speech-to-text engine for voice_check.py (auto, none, voxtype ...)')
    a = ap.parse_args(argv)

    lesson_path = Path(a.lesson).resolve()
    if not lesson_path.is_file():
        say(f'No such file: {a.lesson}')
        return 2
    original = lesson_path.read_text()
    lesson, _ = vc.read_lesson(lesson_path)
    if not isinstance(lesson, dict):
        say('The lesson is not one JSON object. Fix it with scripts/video_check.py first.')
        return 2
    try:
        lines = plan_lines(lesson_path)
    except ValueError as exc:
        say(f'Could not list the narration lines: {exc}')
        return 2
    if not lines:
        say('The lesson has no narration lines ("say" beats). Nothing to make.')
        return 2

    if a.engine == 'none':
        say('Engine: none. No audio was made and the lesson is unchanged. The player will read the captions with the '
            "browser's built-in voice, which it labels as a robotic fallback.")
        return 0
    if not shutil.which('ffmpeg'):
        say('Cannot make clips: ffmpeg is missing. ' + NOT_INSTALLED)
        return 3

    lesson_dir = lesson_path.parent
    out = Path(a.out).resolve() if a.out else lesson_dir / 'audio'
    out.mkdir(parents=True, exist_ok=True)
    wpm = lesson.get('wpm') if isinstance(lesson.get('wpm'), (int, float)) else 145
    a.lesson_wpm = wpm
    if a.speed is not None and not 0.25 <= a.speed <= 4:
        say('--speed must be between 0.25 and 4.')
        return 2
    wanted = sample_lines(lines, a.sample, wpm) if a.sample else lines
    pronounce = lesson.get('pronounce') if isinstance(lesson.get('pronounce'), dict) else {}
    cache = load_cache(out)
    codec = encoder()

    order = ENGINES if a.engine == 'auto' else (a.engine,)
    engine, clips = None, None
    for name in order:
        cand = CLASSES[name](a)
        try:
            cand.check()
            todo = []
            for key, text in wanted:
                tts_text = apply_pronounce(text, pronounce)
                digest = tts_hash(cand.name, cand.voice, cand.full_settings(), tts_text)
                if not cache_hit(cache, cand, key, digest, out):
                    todo.append((key, text, tts_text, digest))
            say(f'Engine: {cand.name}, voice {cand.voice}, speed {cand.speed or 1}. {len(todo)} clip(s) to make, {len(wanted) - len(todo)} already made.')
            t0 = time.time()
            clips = run(cand, lines, todo, out, cache, codec) if todo else dict(cache['clips'])
            engine = cand
            say(f'Made {len(todo)} clip(s) in {time.time() - t0:.0f} s.')
            break
        except Busy as exc:
            say(f'Skipped {name}: {exc}')
            if a.engine != 'auto':
                say('The GPU is busy. Run again later, or add --wait MINUTES to retry. Nothing was stopped.')
                return 3
        except Skip as exc:
            say(f'Skipped {name}: {exc}')
            if a.engine != 'auto':
                say(f'No audio was made: the forced engine {name} did not work. ' + NOT_INSTALLED)
                return 3
        except Broke as exc:
            say(str(exc))
            return 3
        except RuntimeError as exc:
            say(f'Stopped: {exc}')
            return 3
    if engine is None:
        say('Engine: none. No voice engine works here, so no audio was made and the lesson is unchanged. The player '
            "will read the captions with the browser's built-in voice, which it labels as a robotic fallback.")
        return 0

    # Keep only clips for current lines; delete files this tool made for lines that are gone.
    keys = {k for k, _ in lines}
    for key, entry in list(clips.items()):
        if key not in keys:
            (out / str(entry.get('file', ''))).unlink(missing_ok=True)
            del clips[key]
    save_cache(out, engine, clips)

    audio = lesson.get('audio') if isinstance(lesson.get('audio'), dict) else {}
    audio['clips'] = {key: clip_path(out, clips[key]['file'], lesson_dir) for key, _ in lines
                      if key in clips and (out / clips[key]['file']).is_file()}
    # Each clip's real length, so the player and the checker time every line to the voice, not to a word count.
    try:
        audio['seconds'] = {key: clip_seconds(out / clips[key]['file']) for key in audio['clips']}
    except Broke as exc:
        say(str(exc))
        return 3
    audio['voice'] = {'engine': engine.name, 'name': engine.voice, 'disclose': engine.disclose()}
    lesson['audio'] = audio
    write_lesson(lesson_path, lesson, original)
    say(f'Wrote {len(audio["clips"])} clip(s) into "audio" in {lesson_path.name}. {engine.disclose()}')

    if a.sample:
        sample = out / ('sample' + codec[1])
        join_sample([out / clips[k]['file'] for k, _ in wanted], sample, codec[0])
        say(f'Sample: {sample}')

    if a.no_check:
        return 0
    say('Checking the clips with voice_check.py:')
    cmd = [sys.executable, str(HERE / 'voice_check.py'), str(lesson_path), '--audio-dir', str(out), '--asr', a.asr]
    if a.sample:
        cmd.append('--partial')
    r = subprocess.run(cmd)
    return 0 if r.returncode == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
