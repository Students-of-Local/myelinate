# Using Myelinate in Google NotebookLM (Gemini Notebook)

Myelinate works natively in **Google NotebookLM / Gemini Notebook** (`notebooklm.google.com`) using NotebookLM's **10,000-character Custom Chat** instructions and **Studio** study tools—without consuming your course source slots or leaking desktop/IDE commands.

## 60-Second Setup

1. **Create a notebook & upload your course materials**
   - Upload your syllabus, study guide, lecture slides, readings, or notes (PDF, Markdown, Google Docs/Slides, YouTube lectures, audio).
2. **Paste Myelinate into Configure Chat → Custom**
   - Open the **Chat** panel → click **Configure Chat** (sliders icon) → select **Custom**.
   - Paste the full contents of [`configure-chat.txt`](configure-chat.txt) (under 5,000 characters—well inside the 10,000-character cap, leaving room to append your course name, exam date, or study preferences at the bottom).
   - *(On older or constrained surfaces with a 500-character cap, use [`configure-chat-short.txt`](configure-chat-short.txt).)*
3. **Start studying**
   - Ask a question, paste a practice problem, or type `"Map my study guide and quiz me on my weakest objective."`
   - In **real-time voice / Interactive Audio mode**, Myelinate automatically keeps replies to 1–3 spoken sentences with say-back checks.

## Optional: Deep Rubrics & Debrief Handbook (1 Source Slot)

If you want Myelinate's full rubric grading (`assess`), 8-cause returned-exam `debrief` protocol, `assignment` coaching rules, and `study-plan` exam-horizon spacing inside a notebook:

1. Upload [`myelinate-notebooklm-handbook.md`](myelinate-notebooklm-handbook.md) (uses **1** of your 50 free source slots).
2. **Important:** Uncheck `myelinate-notebooklm-handbook.md` in the **Sources** panel before generating Studio **Audio Overviews**, **Video Overviews**, **Flashcards**, **Quizzes**, or **Study Guides**, so Studio draws only from your course materials. Re-check it when chatting if you want deep rubric or debrief coaching.

## Using Studio Tools Without Passive Studying

NotebookLM Studio makes great study artifacts—Myelinate keeps them honest:
- Copy the recipes in [`studio-prompts.md`](studio-prompts.md) into Studio's **Customize** boxes for Audio Overviews, Flashcards, Quizzes, and Study Guides.
- Commit your answer before flipping a Studio flashcard or clicking **Explain**.
- After any Audio or Video Overview, switch to Chat and ask for a **3-question closed-notes transfer check**. Listening feels like learning; unassisted recall proves it.
