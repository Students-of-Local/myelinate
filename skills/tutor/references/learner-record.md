# Learner record: spaced review that survives the session

Chats forget dates and drift. When a learner asks for their progress to be kept, and the assistant can write files (Claude Code, Codex, a desktop app with file access), keep one small local file: `~/.myelinate/learner.json`. In Claude Code, the Myelinate plugin's session hook notes that the file exists, so you can read it and see which reviews are due.

## Rules

- **Only with their OK.** Ask once ("Want me to keep a private record of what you've learned and when to review it, in a file on this computer?"). No answer or no means no file.
- **Local and private.** Never commit it, paste it into a public artifact, or put it in a repository. No health or condition labels, ever; save functional preferences ("short chunks") only if they asked you to keep them.
- **Honest states.** Use the router's topic states and attempt outcomes. A hinted or revealed attempt is not independent success and doesn't move the review date forward.
- **Small.** One entry per target the learner cares about, not per question. Delete entries they've retired.

## Format

```json
{
  "version": 1,
  "learner": { "preferences": ["worked example beside the problem"], "goals": ["CHEM 111 Exam 2, 2026-10-30"] },
  "topics": [
    {
      "topic": "Limiting reactants",
      "course": "CHEM 111",
      "state": "Independent this session",
      "last_outcome": "unassisted-correct",
      "last_reviewed": "2026-10-14",
      "interval_days": 1,
      "next_review": "2026-10-15",
      "notes": "Confuses mole ratio with mass ratio under time pressure"
    }
  ]
}
```

A record can also hold `exams`, one entry per graded exam the learner debriefed (`debrief`). Add it only with their OK, like the rest:

```json
"exams": [
  {
    "course": "CHEM 221",
    "exam": "Exam 2",
    "date": "2026-10-28",
    "score_reported": "71/100",
    "methods": [
      { "method": "built a flashcard deck", "hours": 4, "kind": "making" },
      { "method": "flipped the deck", "hours": 2, "kind": "recognition" },
      { "method": "practice exam, timed", "hours": 0, "kind": "practice" }
    ],
    "misses": { "not-studied": 1, "recognized-not-recalled": 3, "recalled-not-used": 6, "look-alikes": 2, "format": 1, "lost-it": 0, "slip": 1, "time": 0 },
    "change": "10 exam-style questions from memory to end every session from day 5 out",
    "change_done": null
  }
]
```

`kind` is one of: making (building decks, guides, notes or pages), recognition (rereading, watching, flipping cards without answering first), practice (answering from memory, problems, practice tests), spaced (review across days). `score_reported` is the learner's own report; never compute or predict a grade. Set `change_done` at the next debrief: true, false or "partly".

Dates are ISO `YYYY-MM-DD` in the learner's time zone. `state` is one of: Not checked, Needs support, Independent this session, Retrieved after delay, Transferred. `last_outcome` is one of: unassisted-correct, hinted-correct, revealed, incorrect, self-assessed.

## Scheduling the next review

Start from the default ladder, 1 → 3 → 7 → 14 → 30 days, compressed to the exam date (`study-plan` has the horizon rule: the best gap is roughly 20 to 40% of a week-long horizon and 5 to 10% of a year-long one; for an exam in 7 days, review about days 1, 3 and 6).

| Outcome on a review | Next interval |
| --- | --- |
| unassisted-correct | next rung up (1 → 3 → 7 → 14 → 30), capped so the last review lands a day or two before the exam |
| hinted-correct or self-assessed | same interval again |
| revealed or incorrect | back to 1 day, and note the error |

These are product defaults, not a research-optimal schedule; adjust to the learner's errors. A `next_review` date is a suggestion, not a reminder: create calendar reminders only when asked, with a real tool, and confirm them.

## Using it

- **Session start:** read the record (the Claude Code hook only notes that it exists) and pick the entries whose `next_review` has passed; fold 2 to 3 retrieval items on them into the session (after the learner's own question, if they arrived with one).
- **Session end:** update the entries you worked on: outcome, state, `last_reviewed`, `interval_days`, `next_review`. Tell the learner in one line what you saved and when the next review is.
- **On request:** "what's due?" or `/myelinate:review` lists due topics and starts with the first.
