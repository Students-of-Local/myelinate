<p align="center"><img src="assets/hero.svg" alt="Myelinate. Understand it. Retrieve it. Use it. An open-source skill suite for learning: courses, live tutoring, labs, printable tests, flashcards and study plans. Honest, not agreeable, with an adversarial accuracy review before high-stakes material ships." width="100%"></p>

<p align="center">
  <a href="https://github.com/baney75/myelinate/actions/workflows/check.yml"><img src="https://github.com/baney75/myelinate/actions/workflows/check.yml/badge.svg" alt="Package check workflow status"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-a54320" alt="License: MIT"></a>
  <a href="CHANGELOG.md"><img src="https://img.shields.io/badge/version-3.0.0-16313b" alt="Version 3.0.0"></a>
  <a href="#claude-code"><img src="https://img.shields.io/badge/Claude%20Code-plugin-a54320" alt="Claude Code plugin"></a>
</p>

**Learn anything, and learn it well: a class, a language, an instrument, a trade, a codebase. An open-source tutor for your AI assistant that teaches, checks what you can do, and brings it back before you forget.**

Ask about a concept. Bring your course materials if you have them. Myelinate routes the request to the right skill, teaches in manageable steps, and checks what you can do with it. It is honest, not agreeable: it won’t confirm a wrong answer or cave when you push back on a correct correction, and it changes its mind on evidence. It is a set of Markdown skills for a capable AI assistant, not a separate model or a hosted tutoring service. Its examples and depth can fit children, high-school students, university learners, professionals, and people studying on their own.

[Website](https://baney75.github.io/myelinate/) · [Read the router skill](myelinate.md) · [Try the sample lesson](https://baney75.github.io/myelinate/examples/lesson.html) · [See the evidence](references/evidence.md)

**Contents:** [Quick start](#quick-start) · [What's inside](#whats-inside) · [Start with one good question](#start-with-one-good-question) · [What makes the lesson useful](#what-makes-the-lesson-useful) · [Install](#install) · [See the approach](#see-the-approach) · [Evidence](#evidence-without-mythology) · [Improve it](#improve-it)

## Quick start

**Use it in any chat (no install).** Paste this into an assistant that can open links, in chat or voice mode:

```text
Use the Myelinate learning skill: https://github.com/baney75/myelinate — read SKILL.md and follow it to teach me.
```

The assistant fetches [SKILL.md](SKILL.md) and follows it. If yours can't browse, [install the folder](#install) or paste SKILL.md itself.

**Or install it as a Claude Code plugin** (every skill loads by itself when it fits):

```text
/plugin marketplace add baney75/myelinate
/plugin install myelinate@baney75
```

The Claude apps, Codex and other assistants: see [Install](#install).

![Sample Myelinate lesson on limiting reactants](assets/sample-lesson.jpg)

## What's inside

`SKILL.md` is a router. It reads what you are after and hands the request, with your context, to one of twenty skills. Installed as a plugin, each one loads by itself when the moment fits:

| Skill | What it does |
| --- | --- |
| [tutor](skills/tutor/SKILL.md) | For a class you're enrolled in: gathers your syllabus, study guide, notes and textbook (including uploads), then teaches live in chat or voice in your course's scope and notation, one step at a time, with rendered diagrams and interactive 3D models. Loads on its own when the conversation shows the question belongs to a class. |
| [teach](skills/teach/SKILL.md) | For anything you're learning outside a class: a work skill, a language, an instrument, a trade, a sport. Designs the curriculum at your level. For a skill you do with your hands or body, it gives you the whole small version, a drill, how to judge it yourself, and the gate to the next stage. |
| [assignment](skills/assignment/SKILL.md) | Help on homework, lab reports, essays and coding assignments that teaches you to do them instead of doing them for you. Tool steps (drawing a structure, formatting) can be done; the graded thinking stays yours. |
| [project](skills/project/SKILL.md) | Learn while you build something of your own, in the mix you choose: build and learn, teach me to do it, or just tell me how. Stays out of the way of ordinary coding and work. |
| [code](skills/code/SKILL.md) | Learn code you have to own: an inherited repository, a pull request to review, a library, an error you want to understand. Maps it in one picture, traces a real behavior with a prediction first, runs the code for the verdict, and leaves you the one change that carries the idea. Stays off when you only want the code changed. |
| [notes](skills/notes/SKILL.md) | Reads your own notes (Google Drive, OneDrive, Notion, Obsidian or photos of paper) to see how you're grasping it, flags misconceptions and slide-copying, and turns your notes into practice. |
| [assess](skills/assess/SKILL.md) | Formal scored tests and grading against a key and rubric, with honest scores and a gradebook. Quick drills stay in tutor. |
| [course-project](skills/course-project/SKILL.md) | Builds a full course package to run later: level-matched syllabus, lessons, assignments, tests and teacher instructions. Works in a project space or plain chat. |
| [lab](skills/lab/SKILL.md) | Builds interactive learning labs and simulations, shown inline in the chat where the host can, or as a self-contained web page you keep; includes a predict-then-reveal visual stepper. |
| [print](skills/print/SKILL.md) | Paper output, not generic PDF conversion: study guides built for active recall (questions first, answers at the back), practice tests with separate answer keys, labeled and blank diagrams, worksheets. |
| [flashcards](skills/flashcards/SKILL.md) | Makes recall cards ready for Quizlet, Anki or Obsidian; quick live drills stay with the tutor. |
| [game](skills/game/SKILL.md) | Turns an exam's scope into a typed study game: a gate for what must be memorized, surprise recall, a mock in the exam's format and a delayed recheck. Never for graded work. |
| [memory-hooks](skills/memory-hooks/SKILL.md) | Writes research-backed mnemonics for material that will not stick. |
| [study-plan](skills/study-plan/SKILL.md) | Plans study blocks, review and sleep around an exam or study deadline. Creates reminders only with a real, authorized calendar tool. |
| [find-media](skills/find-media/SKILL.md) | Finds learning diagrams, photos, models and videos, with licenses noted. Gives a real, checked link rather than telling you to go search. |
| [video](skills/video/SKILL.md) | Turns a video, lecture, playlist or transcript into something you can do: recall before any summary, questions and cards pointed at timestamps. |
| [progress](skills/progress/SKILL.md) | The moments around the learning: wrapping up a session, coming back after a gap, not being able to start, "how am I doing?" and "am I ready?", answered from what you did unaided and never with a predicted score. |
| [debrief](skills/debrief/SKILL.md) | A graded exam, quiz or practical came back. Sorts every miss by its cause (never studied, recognized but not recalled, recalled but not used, mixed up look-alikes, format, lost it, slip, time), checks each with a cold retest, ties the causes to how you studied, and schedules one change for the next exam. Keeps a ledger across exams if you want one. |
| [teacher](skills/teacher/SKILL.md) | For teachers and trainers: unit and lesson plans built backward from the outcome, rubrics with observable levels, quizzes and differentiation. |
| [verify](skills/verify/SKILL.md) | Checks learning material and answer keys for accuracy and currency before use; software code review stays elsewhere. |

When a concept has shape (a molecule in 3D, a conformation, a mechanism, a curve), Myelinate renders it and gives you the controls instead of describing it in a paragraph, linked to the notation your course uses. Visuals appear inline, right in the conversation, wherever your assistant can draw there (claude.ai's inline visuals, for example): practice questions, flashcards, step-through figures, graphs with sliders and videos with pause questions. Everywhere else you get a page you can open, and you can ask for a file or a printable any time. A concept map, mechanism stepper or faded worked example can make you fill the missing link or predict the next step before reveal. It saves nothing unless you ask. If you want it to remember how you learn (pace, chunk size, what's hard) or what's due for review, it gives you a short profile to keep, or, where it can write files, a private record on your computer that it reads when you come back. Sharing a learning condition is optional and never required.

## Start with one good question

```text
Use $myelinate to teach me limiting reactants.
I understand moles, but I keep choosing the wrong reactant.
I have 20 minutes. Explain first, then help me practice.
```

Or:

```text
Use $myelinate with my study guide and notes.
Map the tested objectives, teach my weak spots, and give me
new problems in the format my course uses.
```

The tutor asks about the goal, course context, and optional access preferences. For courses, it asks for the **study guide, syllabus, notes/slides, and textbook edition**. Missing materials do not block a first lesson. It asks how you learn, such as pacing, chunk size, or what's hard. You may mention a learning condition if you choose, but it is never required and never labeled; “shorter steps help” is enough.

## What makes the lesson useful

| From the learner | From Myelinate |
| --- | --- |
| “I don't get it.” | A clear explanation, a worked example, and the limits of the analogy. |
| “I think I know it.” | A question you answer before seeing the solution, with specific feedback. |
| “I can do that example.” | A changed application that checks whether you can choose and use the idea. |
| “My exam is next week.” | Course-aligned practice and a realistic queue for revisiting the gaps. |
| “I need a different pace.” | Options for chunk size, steps, response format, and distractions. |
| “Make me something I can study.” | A source-linked study pack with original practice and a separate explained answer key. |

**Explain → retrieve → get feedback → apply → revisit.** The sequence adapts. You can ask for an explanation, request a hint, skip a test, or stop at any time. Flashcards are available when useful; application stays central.

## Install

Myelinate is one plugin for Claude Code, the Claude apps (claude.ai, desktop), ChatGPT and Codex, Grok, Cursor and Gemini CLI. Every skill ships in its own folder with the references and templates it uses, so it works the same wherever it's installed.

### Claude Code

```text
/plugin marketplace add baney75/myelinate
/plugin install myelinate@baney75
```

Each skill then loads by itself when it fits; force one with `/myelinate:myelinate` (the router), `/myelinate:tutor`, `/myelinate:code`, and so on. Claude Code also gets:

- **Loads when you're learning.** A short session note tells Claude to load the matching Myelinate skill for a learning question, even a quick one, and not for work you want done. Create the file `~/.myelinate/no-hint` to turn it off.
- `/myelinate:quiz <topic>`, `/myelinate:review` (what's due today, retrieval first), `/myelinate:wrap` (end a session with one recall and the next step), `/myelinate:progress` (how it's really going) and `/myelinate:video <link or topic>`.
- **Spaced review across sessions.** If you ask Myelinate to keep your progress, it saves a private record at `~/.myelinate/learner.json`, and each new session can see which reviews are due. Without a record, nothing changes.
- **An answer-key agent** (`key-worker`) that solves a problem without seeing your answer, so the verdict can't drift toward what you said.
- **The Myelinate output style** (pick it in `/config`): Claude does the engineering and hands you one decision at a time.

**Updates.** The plugin carries no fixed version, so Claude Code updates it whenever the repository changes. Turn on auto-update for the `baney75` marketplace under `/plugin` → Marketplaces, or run `claude plugin update myelinate@baney75`. To follow a branch instead of `main`, add the marketplace as `baney75/myelinate#<branch>`.

### Claude apps (claude.ai and desktop)

In **Customize → Plugins**, choose **Add marketplace** and enter `baney75/myelinate`, then install **myelinate**. Or download `myelinate-plugin.zip` from the [latest release](https://github.com/baney75/myelinate/releases/latest) and use **Add → Upload plugin**. If you installed an older Myelinate as a skill, remove it first so only one copy is listed.

### Codex

The repository is a Codex plugin marketplace (`.agents/plugins/marketplace.json`, manifest `.codex-plugin/plugin.json`). Add it as a marketplace in Codex, or clone it and link one skill folder at a time into `~/.agents/skills` (each folder is self-contained):

```sh
git clone https://github.com/baney75/myelinate.git
mkdir -p ~/.agents/skills
for d in myelinate/skills/*/; do ln -s "$PWD/$d" ~/.agents/skills/"$(basename "$d")"; done
```

### ChatGPT

Search for Myelinate in the ChatGPT plugin directory once it's listed. Until then, paste the link (Quick start).

### Grok Build

```sh
grok plugin marketplace add baney75/myelinate
grok plugin install myelinate@baney75 --trust
```

### Cursor

Search for Myelinate in the Cursor marketplace once it's listed. Until then, add the repository as a local plugin.

### Gemini CLI

```sh
gemini extensions install https://github.com/baney75/myelinate
```

### Any tool that reads Agent Skills

```sh
npx skills add baney75/myelinate
```

### Any other assistant

Paste the link (Quick start), or provide [SKILL.md](SKILL.md) as instructions. The router works alone. If the assistant can open the repository, the sub-skills sit beside it under `skills/`.

**Stopping it.** Tell your assistant where you don't want Myelinate ("don't tutor me on my coding projects", "just answer my Spanish questions"). It respects that scope; a slash command still works when you want it. Ordinary coding, building and work requests don't trigger it in the first place.

No account, API key or package installation is required. Your assistant's ordinary access, tools and usage limits still apply.

## What it runs, reads and sends

Myelinate is instructions, templates and a few small local scripts. It has no server, account, API key, tracking or telemetry, and it sends nothing anywhere on its own. Full policy: [PRIVACY.md](PRIVACY.md); terms: [TERMS.md](TERMS.md).

- **Session hook (Claude Code and Grok Build).** `hooks/session-start.sh` runs locally at session start. It prints a line telling the assistant when to load a learning skill and, if you keep a learner record, notes that the file exists. It reads no file and touches no network. Create `~/.myelinate/no-hint` to turn it off.
- **Your learner record and profile** are written only when you ask, and stay on your machine. The record holds topics, courses and review dates. Myelinate tells the assistant to keep health and condition labels out of it, but it's plain text the assistant writes, so check it if that matters to you.
- **Printing.** `print` may run `scripts/make_pdf.py`, which renders an HTML page to PDF with your local headless Chromium; a web font or image the page links to is loaded while rendering.
- **Video pages.** A page Myelinate makes with a YouTube player loads it from `youtube-nocookie.com` only when you press play, and shows a thumbnail from `i.ytimg.com`. YouTube's own terms and privacy policy apply to those.
- **Your assistant's own tools.** Source checks, video searches, YouTube's public oEmbed check and `verify` use your assistant's web search and fetch when the task calls for them. If you have `yt-dlp` and a shell, `video` can use it for captions.

## See the approach

The [interactive sample](https://baney75.github.io/myelinate/examples/lesson.html) teaches limiting reactants with a worked example, a fresh numerical problem, hints, and answer feedback. It distinguishes independent, hinted, and revealed work. It does not collect responses or pretend to measure long-term retention. [Open the source](examples/lesson.html) to use it offline.

For course material, Myelinate can produce a compact scope map, concept explanation, practice set, explained answer key, and review queue. The included [templates](references/session-template.md) keep those outputs consistent without forcing every lesson into a document.

## Evidence without mythology

Retrieval, spacing, feedback, and worked examples have substantial research behind them. Their effects depend on the task, learner, timing, and comparison. The [evidence ledger](references/evidence.md) links the sources, inspected scope, and limits. [How the mind learns](references/how-the-mind-learns.md) explains the memory mechanisms behind each tutoring rule (prediction error, generation, consolidation, metacognitive illusions) and the limits of the myelination evidence, which is mostly from mice. The [research method](references/research-method.md) explains how the tutor evaluates sources for a new topic.

“Myelinate” is a name, not a claim that a prompt changes your myelin. This package cannot force permanent memory or guarantee a grade. A good-looking study guide is not a learning outcome. The tutor reports actual attempts and delays; the complete skill's learning efficacy has not been established.

Learner health disclosures and course records stay out of public outputs. Saving preferences or progress requires agreement. A suggested review time is not a scheduled notification.

## Improve it

Useful contributions include a reproducible tutoring failure, a better-supported source, an accessibility fix, or a clearer exercise. Use fictional or consented, de-identified examples; do not upload private course material, learner health information, or restricted exams. See [CONTRIBUTING.md](CONTRIBUTING.md) for the checks to run, [CHANGELOG.md](CHANGELOG.md) for what changed in each version, [SECURITY.md](SECURITY.md) for prompt-injection and privacy reports, and [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) for how we work together. To cite Myelinate, use [CITATION.cff](CITATION.cff).

```sh
python3 scripts/check.py          # package integrity and local links
python3 scripts/check.py --sync   # regenerate SKILL.md after editing myelinate.md
```

`myelinate.md` is the authored source; `SKILL.md` is an identical generated entrypoint for skill discovery. [Behavioral scenarios](evals/scenarios.md) test decisions that a syntax checker cannot. [Verification notes](evals/verification.md) describe what has actually been checked.

MIT licensed. Research and linked third-party material retain their own rights.

## Sponsors

<!-- sponsors:start -->
No sponsors yet. [Sponsor on GitHub](https://github.com/sponsors/baney75) and your name appears here automatically.
<!-- sponsors:end -->

## Credits

Learning visual patterns were adapted from Nico Bailon's visual-explainer. See [NOTICE.md](NOTICE.md) for attribution and license notice.
