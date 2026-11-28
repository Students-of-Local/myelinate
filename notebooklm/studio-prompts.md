# Myelinate Studio Prompts for Google NotebookLM (Gemini Notebook)

Copy and paste these into NotebookLM's **Studio → Customize** prompt boxes so generated Audio Overviews, Flashcards, Quizzes, and Study Guides stay aligned with active recall and Socratic honesty.

> **Tip:** If you uploaded `myelinate-notebooklm-handbook.md` as a source, **uncheck it in the Sources panel** before generating any Studio artifact so only your course materials are used.

---

## 1. Audio Overview (Socratic / Critique / Debate)
Use with **Critique**, **Debate**, or **Deep Dive → Customize**:

```text
Focus strictly on the uploaded course materials and study guide objectives. Instead of summarizing passively, structure the discussion around the 4–6 hardest concepts and most common student misconceptions. Before explaining each mechanism or contrast (e.g., look-alike concepts), pose a clear prediction question and pause briefly so the listener can commit an answer. Explicitly contrast confusable pairs and state what the exam tests versus background detail. Never invent facts outside the sources.
```

*(After listening, go to Chat and type: "I just listened to the Audio Overview—test me with 3 closed-notes transfer questions.")*

---

## 2. Studio Flashcards (Atomic Recall & Contrasts)
Use in **Studio → Flashcards → Customize**:

```text
Generate atomic, one-answer flashcards strictly from the uploaded course materials and study guide. Use a mix of: (1) mechanism "why" questions, (2) explicit contrast cards for confusable look-alike concepts, and (3) short application scenarios—avoid vague summary cards and yes/no prompts. Keep backs to one concise line with units where applicable. Tag or reference the source section on each card. Do not invent facts outside the uploaded sources.
```

---

## 3. Studio Quiz (Misconception-Grounded Diagnostics)
Use in **Studio → Quiz → Customize**:

```text
Build exam-style diagnostic questions strictly grounded in the uploaded course materials and study guide objectives. Weight items toward application, transfer, and distinguishing look-alike concepts rather than verbatim recall. Design every wrong option around a realistic student misconception (sign errors, reversed causation, confused definitions) rather than joke distractors. Cite the exact source section in explanations.
```

---

## 4. Studio Study Guide / Report (Questions-First Active Recall)
Use in **Studio → Reports / Study Guide → Customize**:

```text
Create an active-recall study guide organized by the uploaded study guide objectives—not a passive summary. For each objective: (1) list 2–3 retrieval and application questions FIRST with blank space to answer from memory, (2) include one compact contrast table for confusable terms or mechanisms, and (3) place all worked answers and source citations in a separate Answer Key section at the very end so the learner can test themselves before looking. Flag any objective missing from the uploaded slides or notes.
```
