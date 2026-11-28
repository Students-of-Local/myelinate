#!/usr/bin/env python3
"""Build Myelinate's plugin package and verify it.

Hosts install a plugin skill by skill, and some copy only a skill's own
folder. So every skill folder carries a copy of each shared file it names
(references, templates, examples, scripts, assets), and the router gets a
folder of its own at skills/myelinate. The sources stay at the repository
root; the copies are generated here and checked for drift.

    python3 scripts/package.py build    # regenerate copies, dist/myelinate-plugin.zip and dist/myelinate-codex.zip
    python3 scripts/package.py verify   # fail on drift or any referenced path missing from the zip
"""
import re
import sys
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
SHARED = ('references', 'templates', 'examples', 'scripts', 'assets')
# Paths that belong to the dbaney.com site repository, named in lab instructions.
EXTERNAL = {'scripts/learning-lab.mjs', 'scripts/icons.mjs'}
ZIP = ROOT / 'dist' / 'myelinate-plugin.zip'
# Files and folders that make up the installed plugin.
PLUGIN_FILES = ['.claude-plugin/plugin.json', '.codex-plugin/plugin.json', 'LICENSE', 'NOTICE.md', 'README.md', 'PRIVACY.md', 'assets/icon.png']
PLUGIN_DIRS = ['skills', 'output-styles', 'commands', 'agents', 'hooks']
# OpenAI's plugin directory takes skills, with the manifest at the top of the zip. It takes no hooks.
CODEX_ZIP = ROOT / 'dist' / 'myelinate-codex.zip'
CODEX_FILES = ['.codex-plugin/plugin.json', 'LICENSE', 'README.md', 'PRIVACY.md', 'TERMS.md']
# OpenAI's directory bars local tools that fetch from third-party sites: the YouTube finder stays out of its zip.
CODEX_EXCLUDE = ('scripts/yt.py',)
# Google NotebookLM / Gemini Notebook export: Custom Chat persona (<= 9,500 chars under 10k cap)
# plus one optional clean-room handbook source and Studio Customize prompt recipes.
NOTEBOOKLM_ZIP = ROOT / 'dist' / 'myelinate-notebooklm.zip'
NOTEBOOKLM_DIR = ROOT / 'notebooklm'
NOTEBOOKLM_HANDBOOK = NOTEBOOKLM_DIR / 'myelinate-notebooklm-handbook.md'
NOTEBOOKLM_CHAT_MAX = 9500
NOTEBOOKLM_SHORT_MAX = 490
NOTEBOOKLM_HANDBOOK_MAX_WORDS = 50000
NOTEBOOKLM_HANDBOOK_SKILLS = ('tutor', 'assignment', 'assess', 'debrief', 'study-plan', 'flashcards', 'verify')
NOTEBOOKLM_LEAK_RE = re.compile(
    r'show_widget|/myelinate:|CLAUDE_PLUGIN_ROOT|session-start\.sh|learner\.json|yt-dlp|make_pdf\.py'
    r'|\.\./[a-z-]+/SKILL\.md|skills/[a-z-]+/SKILL\.md|<!--\s*local-tools\s*-->',
    re.I,
)
INVISIBLE_UNICODE_RE = re.compile(r'[\u200b-\u200f\u202a-\u202e\u2060\u2066-\u2069]')


def codex_excluded(rel):
    return any(rel == x or rel.endswith('/' + x) for x in CODEX_EXCLUDE)

SHARED_RE = re.compile(r"(?<![/\w.<>…-])((?:%s)/[\w.-]+\.[a-z0-9]+)" % '|'.join(SHARED))
SIBLING_RE = re.compile(r"(?<![/\w.<>…-])\.\./([a-z-]+)/SKILL\.md")
REPO_SKILL_RE = re.compile(r"(?<![/\w.<>…-])skills/([a-z-]+)/SKILL\.md")
BARE_MD_RE = re.compile(r"(?<![/\w.<>…-])([a-z][a-z0-9-]*\.md)\b")


def skill_names():
    return sorted(p.parent.name for p in (ROOT / 'skills').glob('*/SKILL.md') if p.parent.name != 'myelinate')


def localize(text):
    """Rewrite repository-root skill paths to sibling paths (relative to a skill folder)."""
    return REPO_SKILL_RE.sub(r'../\1/SKILL.md', text)


def shared_refs(text, in_references=False):
    refs = set(SHARED_RE.findall(text))
    if in_references:
        refs |= {f'references/{name}' for name in BARE_MD_RE.findall(text) if (ROOT / 'references' / name).is_file()}
    return {r for r in refs if r not in EXTERNAL}


def closure(entry_text):
    """Every shared file a skill needs: what its SKILL.md names, plus what those files name."""
    todo, seen = list(shared_refs(entry_text)), set()
    while todo:
        rel = todo.pop()
        if rel in seen or not (ROOT / rel).is_file():
            seen.add(rel)
            continue
        seen.add(rel)
        if rel.endswith('.md'):
            todo += shared_refs((ROOT / rel).read_text(), rel.startswith('references/'))
    return sorted(seen)


def generated(skill):
    """Map of path (relative to ROOT) -> bytes for one skill's generated files."""
    out = {}
    if skill == 'myelinate':
        entry = localize((ROOT / 'myelinate.md').read_text())
        out['skills/myelinate/SKILL.md'] = entry.encode()
        out['skills/myelinate/agents/openai.yaml'] = (ROOT / 'agents' / 'openai.yaml').read_bytes()
    else:
        entry = (ROOT / 'skills' / skill / 'SKILL.md').read_text()
    for rel in closure(entry):
        src = ROOT / rel
        if not src.is_file():
            continue  # verify() reports it
        data = src.read_bytes()
        if src.suffix == '.md':
            data = localize(data.decode()).encode()
        out[f'skills/{skill}/{rel}'] = data
    return out


def all_generated():
    out = {}
    for skill in ['myelinate'] + skill_names():
        out.update(generated(skill))
    return out


def owned_paths():
    """Existing files the build owns: the router folder and shared-file copies in skill folders."""
    paths = set()
    for d in (ROOT / 'skills').iterdir():
        if not d.is_dir():
            continue
        if d.name == 'myelinate':
            paths |= {p for p in d.rglob('*') if p.is_file()}
        for sub in SHARED:
            if (d / sub).is_dir():
                paths |= {p for p in (d / sub).rglob('*') if p.is_file()}
    return {str(p.relative_to(ROOT)) for p in paths if p.name != '.DS_Store'}


LOCAL_TOOLS = re.compile(rb'<!-- local-tools -->.*?<!-- /local-tools -->\n?', re.S)


def build_zip(files, path=ZIP, prefix='myelinate/', transform=None):
    path.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        for rel in sorted(files):
            info = zipfile.ZipInfo(f'{prefix}{rel}', date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            data = (ROOT / rel).read_bytes()
            z.writestr(info, transform(rel, data) if transform else data)


def codex_transform(rel, data):
    """OpenAI's directory bars fetching from third-party sites with local tools, so those steps stay out of its zip."""
    return LOCAL_TOOLS.sub(b'', data) if rel.endswith('.md') else data


def _strip_notebooklm_host_lines(text):
    """Sanitize a skill markdown file for NotebookLM: remove frontmatter, local-tools, and IDE/Claude-only paths."""
    text = re.sub(r'^---\n.*?\n---\n+', '', text, count=1, flags=re.S)
    text = LOCAL_TOOLS.sub(b'', text.encode()).decode()
    out = []
    for line in text.splitlines():
        if line.startswith('Paths like `references/'):
            continue
        if line.startswith('Other Myelinate skills are siblings'):
            continue
        if NOTEBOOKLM_LEAK_RE.search(line):
            # Rewrite sibling skill references cleanly; drop lines that are purely local-tool/IDE instructions.
            cleaned = re.sub(r'`\.\./([a-z-]+)/SKILL\.md`', r'`\1`', line)
            cleaned = re.sub(r'`skills/([a-z-]+)/SKILL\.md`', r'`\1`', cleaned)
            cleaned = re.sub(r'/myelinate:([a-z-]+)', r'"\1"', cleaned)
            if NOTEBOOKLM_LEAK_RE.search(cleaned):
                continue
            line = cleaned
        out.append(line)
    return '\n'.join(out).strip()


def build_notebooklm_handbook():
    """Generate one clean-room Markdown handbook source for Google NotebookLM (1 of 50 free slots)."""
    header = (
        '# Myelinate Pedagogy Handbook (Google NotebookLM / Gemini Notebook)\n\n'
        '> **PEDAGOGY MANUAL ONLY — NOT COURSE CONTENT.**\n'
        '> Never cite this file as subject-matter evidence for the learner\'s course.\n'
        '> Uncheck this source in the Sources panel before generating Studio Audio Overviews, '
        'Video Overviews, Flashcards, Quizzes, or Study Guides.\n\n'
    )
    sections = []
    for name in NOTEBOOKLM_HANDBOOK_SKILLS:
        raw = (ROOT / 'skills' / name / 'SKILL.md').read_text(encoding='utf-8')
        body = _strip_notebooklm_host_lines(raw)
        sections.append(f'---\n\n{body}')
    return (header + '\n\n'.join(sections) + '\n').encode('utf-8')


def notebooklm_files():
    rels = [
        'notebooklm/configure-chat.txt',
        'notebooklm/configure-chat-short.txt',
        'notebooklm/myelinate-notebooklm-handbook.md',
        'notebooklm/studio-prompts.md',
        'notebooklm/SETUP.md',
        'LICENSE',
        'PRIVACY.md',
    ]
    return [r for r in rels if (ROOT / r).is_file()]


def plugin_files():
    files = [f for f in PLUGIN_FILES if (ROOT / f).is_file()]
    for d in PLUGIN_DIRS:
        files += [str(p.relative_to(ROOT)) for p in sorted((ROOT / d).rglob('*'))
                  if p.is_file() and p.name != '.DS_Store']
    return files


def codex_files():
    import json
    ui = json.loads((ROOT / '.codex-plugin/plugin.json').read_text()).get('interface', {})
    icons = sorted({ui[k].removeprefix('./') for k in ('composerIcon', 'logo') if ui.get(k)})
    files = [f for f in CODEX_FILES + icons if (ROOT / f).is_file()]
    return [f for f in files if not codex_excluded(f)] + [
        str(p.relative_to(ROOT)) for p in sorted((ROOT / 'skills').rglob('*'))
        if p.is_file() and p.name != '.DS_Store' and not codex_excluded(str(p.relative_to(ROOT)))]


def build():
    for rel in owned_paths():
        (ROOT / rel).unlink()
    for rel, data in all_generated().items():
        dest = ROOT / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
    for d in sorted((ROOT / 'skills').rglob('*'), reverse=True):
        if d.is_dir() and not any(d.iterdir()):
            d.rmdir()
    if NOTEBOOKLM_DIR.is_dir():
        NOTEBOOKLM_HANDBOOK.write_bytes(build_notebooklm_handbook())
    build_zip(plugin_files())
    build_zip(codex_files(), CODEX_ZIP, '', codex_transform)
    if NOTEBOOKLM_DIR.is_dir():
        build_zip(notebooklm_files(), NOTEBOOKLM_ZIP, 'myelinate-notebooklm/')
    print(f'built {len(all_generated())} generated files, {ZIP.relative_to(ROOT)}, {CODEX_ZIP.relative_to(ROOT)} and {NOTEBOOKLM_ZIP.relative_to(ROOT)}')


def verify():
    errors = []
    want = all_generated()
    have = owned_paths()
    for rel, data in want.items():
        if rel not in have or (ROOT / rel).read_bytes() != data:
            errors.append(f'{rel}: out of date; run python3 scripts/package.py build')
    for rel in sorted(have - set(want)):
        errors.append(f'{rel}: stale generated file; run python3 scripts/package.py build')
    if not ZIP.is_file():
        build_zip(plugin_files())  # the zip is a build artifact; the committed copies are what must not drift
    with zipfile.ZipFile(ZIP) as z:
        names = {n[len('myelinate/'):] for n in z.namelist()}
        zipped = {n[len('myelinate/'):]: z.read(n) for n in z.namelist()}
    for rel in plugin_files():
        if rel not in names or zipped[rel] != (ROOT / rel).read_bytes():
            errors.append(f'{ZIP.relative_to(ROOT)}: {rel} missing or stale; run python3 scripts/package.py build')
    if not CODEX_ZIP.is_file():
        build_zip(codex_files(), CODEX_ZIP, '', codex_transform)
    with zipfile.ZipFile(CODEX_ZIP) as z:
        codex = {n: z.read(n) for n in z.namelist()}
    for rel in codex_files():
        if codex.get(rel) != codex_transform(rel, (ROOT / rel).read_bytes()):
            errors.append(f'{CODEX_ZIP.relative_to(ROOT)}: {rel} missing or stale; run python3 scripts/package.py build')
    for rel in sorted(set(codex) - set(codex_files())):
        errors.append(f'{CODEX_ZIP.relative_to(ROOT)}: {rel} is not part of the plugin; run python3 scripts/package.py build')
    for rel in sorted(n for n in codex if codex_excluded(n)):
        errors.append(f'{CODEX_ZIP.relative_to(ROOT)}: {rel} is a local tool that fetches from a third-party site; '
                      "OpenAI's directory bars it")
    # With the local-tools blocks stripped, every path a Codex skill names must still be in its zip.
    for rel in sorted(n for n in codex if n.startswith('skills/') and n.endswith('.md')):
        base = '/'.join(rel.split('/')[:2])
        for ref in shared_refs(codex[rel].decode()):
            if f'{base}/{ref}' not in codex:
                errors.append(f'{CODEX_ZIP.relative_to(ROOT)}: {rel} names {ref}, missing from the Codex zip')
    # Every path a skill or its copied files name must exist in the zip.
    counts = {}
    skills = sorted({PurePosixPath(n).parts[1] for n in names if n.startswith('skills/') and n.endswith('/SKILL.md')})
    for skill in skills:
        base = f'skills/{skill}'
        n = 0
        for rel in sorted(x for x in names if x.startswith(base + '/') and x.endswith('.md')):
            text = zipped[rel].decode()
            in_refs = '/references/' in rel
            for ref in shared_refs(text):
                n += 1
                if f'{base}/{ref}' not in names:
                    errors.append(f'{rel}: names {ref}, missing from the package at {base}/{ref}')
            for sib in SIBLING_RE.findall(text):
                n += 1
                if f'skills/{sib}/SKILL.md' not in names:
                    errors.append(f'{rel}: names ../{sib}/SKILL.md, missing from the package')
            if in_refs:
                for bare in BARE_MD_RE.findall(text):
                    if (ROOT / 'references' / bare).is_file():
                        n += 1
                        if f'{base}/references/{bare}' not in names:
                            errors.append(f'{rel}: names {bare}, missing from the package')
        counts[skill] = n
    router = zipped.get('skills/myelinate/SKILL.md', b'').decode()
    for name in skill_names():
        if f'../{name}/SKILL.md' not in router:
            errors.append(f'skills/myelinate/SKILL.md does not route to ../{name}/SKILL.md')
    # Verify Google NotebookLM / Gemini Notebook export bundle.
    if NOTEBOOKLM_DIR.is_dir():
        want_hb = build_notebooklm_handbook()
        if not NOTEBOOKLM_HANDBOOK.is_file() or NOTEBOOKLM_HANDBOOK.read_bytes() != want_hb:
            errors.append('notebooklm/myelinate-notebooklm-handbook.md: out of date; run python3 scripts/package.py build')
        chat_path = NOTEBOOKLM_DIR / 'configure-chat.txt'
        short_path = NOTEBOOKLM_DIR / 'configure-chat-short.txt'
        for p, limit in ((chat_path, NOTEBOOKLM_CHAT_MAX), (short_path, NOTEBOOKLM_SHORT_MAX)):
            if not p.is_file():
                errors.append(f'{p.relative_to(ROOT)}: missing NotebookLM prompt file')
                continue
            txt = p.read_text(encoding='utf-8')
            if len(txt) > limit:
                errors.append(f'{p.relative_to(ROOT)}: {len(txt)} chars exceeds NotebookLM limit ({limit})')
            if NOTEBOOKLM_LEAK_RE.search(txt):
                errors.append(f'{p.relative_to(ROOT)}: contains non-NotebookLM host/tool reference ({NOTEBOOKLM_LEAK_RE.search(txt).group(0)!r})')
            if INVISIBLE_UNICODE_RE.search(txt):
                errors.append(f'{p.relative_to(ROOT)}: contains invisible/bidi Unicode')
        if NOTEBOOKLM_HANDBOOK.is_file():
            hb_txt = NOTEBOOKLM_HANDBOOK.read_text(encoding='utf-8')
            if 'PEDAGOGY MANUAL ONLY' not in hb_txt[:500]:
                errors.append('notebooklm/myelinate-notebooklm-handbook.md: missing PEDAGOGY MANUAL ONLY isolation header')
            if len(hb_txt.split()) > NOTEBOOKLM_HANDBOOK_MAX_WORDS:
                errors.append(f'notebooklm/myelinate-notebooklm-handbook.md: exceeds {NOTEBOOKLM_HANDBOOK_MAX_WORDS} words')
            if NOTEBOOKLM_LEAK_RE.search(hb_txt):
                errors.append(f'notebooklm/myelinate-notebooklm-handbook.md: leaks host/tool reference ({NOTEBOOKLM_LEAK_RE.search(hb_txt).group(0)!r})')
            if INVISIBLE_UNICODE_RE.search(hb_txt):
                errors.append('notebooklm/myelinate-notebooklm-handbook.md: contains invisible/bidi Unicode')
        if not NOTEBOOKLM_ZIP.is_file():
            build_zip(notebooklm_files(), NOTEBOOKLM_ZIP, 'myelinate-notebooklm/')
        with zipfile.ZipFile(NOTEBOOKLM_ZIP) as z:
            nb_names = {n[len('myelinate-notebooklm/'):] for n in z.namelist()}
            for rel in notebooklm_files():
                if rel not in nb_names:
                    errors.append(f'{NOTEBOOKLM_ZIP.relative_to(ROOT)}: {rel} missing; run python3 scripts/package.py build')
    return errors, counts


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'verify'
    if cmd == 'build':
        build()
    errors, counts = verify()
    if errors:
        print('\n'.join(errors), file=sys.stderr)
        sys.exit(1)
    total = sum(counts.values())
    print(f'PASS: {len(counts)} skills in {ZIP.relative_to(ROOT)}; all {total} referenced paths present in the package')
    for skill, n in counts.items():
        print(f'  {skill}: {n} paths')
