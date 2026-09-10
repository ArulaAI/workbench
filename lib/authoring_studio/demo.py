"""Opt-in, offline recording scenario. Never falls through to a model provider."""
import copy
import json
import time
from pathlib import Path

from .generator import source
from .models import Clarification, Generation
from .workflow import intake_for

DEMO_ID = "task-due-dates"
DEMO_BRIEF = "When I add a task, it is not always something I need to do today. I might need to cancel a subscription by next week, but newer tasks push it down the list and I miss the deadline. Add an optional due date to tasks. Highlight tasks due today, tomorrow or the day after tomorrow, and show earlier due dates before later or undated tasks. The backend will return the highlight color as a hex code for clients to use."
DEMO_TITLE = "Due dates for tasks"
DELAY_SECONDS = 5
REVIEW_PREFIX = "Apply these author answers to the "
REVIEW_SEPARATOR = "\n\nAuthor answers:\n"


def question(id, text, why, options):
    return {"id": id, "question": text, "why": why,
            "options": [{"label": label, "description": description} for label, description in options]}


QUESTIONS = [
    question("overdue", "What should happen when an unfinished task is overdue?",
             "This defines its position and highlight after the date passes.", [
        ("Keep overdue tasks at the top", "Show overdue tasks before other active tasks, oldest due date first, with an overdue highlight."),
        ("Keep overdue tasks in their current position", "Do not move overdue tasks; show an overdue highlight in their existing position."),
        ("Use a separate overdue group", "Place overdue tasks in their own group above the remaining active list, oldest due date first.")]),
    question("editing", "Can users change or remove a due date after creating a task?",
             "The PRD needs a clear rule for rescheduling a deadline.", [
        ("Allow changing and removing dates", "Users can edit or clear a due date. The backend updates ordering and highlight metadata on the next read."),
        ("Only set the date at creation", "A due date can only be set when the task is created; later changes or removal are not allowed."),
        ("Allow changing but not removing dates", "Users can move a due date to another date, but cannot clear it once it has been set.")]),
    question("completed", "How should completed tasks behave?",
             "This prevents finished work from competing with active deadlines.", [
        ("Keep the existing completed-task view", "Exclude completed tasks from active due-date sorting and highlighting, preserving the existing completed-task view."),
        ("Show completed tasks at the bottom", "Keep completed tasks at the bottom of the list without urgency highlighting."),
        ("Hide completed tasks from the default list", "Exclude completed tasks from the default list and show them only when the completed filter is selected.")]),
]


def review_target(text, kind):
    """Only the existing review form's explicit operation is scripted."""
    if REVIEW_SEPARATOR not in text:
        return None
    if text.startswith(REVIEW_PREFIX + "Success publication review.") and kind == "prd":
        return "success"
    if text.startswith(REVIEW_PREFIX + "Open questions publication review."):
        return "risks" if kind == "prd" else "decisions"
    return None


def load_document(kind):
    return json.loads((Path(__file__).parent / "examples" / f"due_date_{kind}.json").read_text())


class DemoGenerator:
    def __call__(self, state, operation, head, upstream):
        kind = operation["kind"]
        if kind not in ("prd", "rfc"):
            raise ValueError("This saved example includes PRD and RFC. Start a regular workspace to generate a Design spec.")
        # Outside the database transaction. Normal cancellation and stale-result
        # checks still apply when the worker returns.
        time.sleep(DELAY_SECONDS)
        evidence = [source("Saved due-date demo brief", state["brief"], limit=20000)]
        model = "saved-example/task-due-dates-v1 (no AI)"
        if operation["action"] == "clarify":
            return Clarification(summary="Review these three decisions before opening the saved PRD example." if kind == "prd" else "The saved RFC example can use the selected sources directly.",
                                 workspace_title=DEMO_TITLE, questions=QUESTIONS if kind == "prd" else []), evidence, model
        if head:
            target = review_target(operation["text"], kind)
            if not target or operation["section_id"] != target:
                raise ValueError("This example does not use AI for chat changes. Use Edit for document changes, or enter an answer in the publication review.")
            answer = operation["text"].split(REVIEW_SEPARATOR, 1)[1].strip()
            if not answer:
                raise ValueError("Enter your review answer first.")
            section = copy.deepcopy(next(s for s in head["sections"] if s["id"] == target))
            # Save verbatim author input. No inference, invented resolution or
            # edits to other sections. The UI explicitly describes replacement.
            section["body"] = "Author-provided " + ("success criteria" if target == "success" else "review decision") + ":\n\n" + answer
            section["items"] = []
            evidence.append(source("Author's demo review answer", answer, limit=20000))
            section["source_ids"] = [evidence[-1]["id"]]
            patch = {key: section[key] for key in ("id", "body", "items", "source_ids")}
            # Preserve separately tracked questions: without AI we cannot infer
            # which of these an arbitrary answer resolves.
            return Generation(summary="Saved your review answer as written. Review this new version before publishing.", sections=[patch],
                              questions=head["questions"], coverage=head["coverage"]), evidence, model

        data = load_document(kind)
        intake = intake_for(state, "prd") or {}
        answers = intake.get("answers", {})
        if kind == "prd":
            decisions = "\n\n## Saved author decisions\n\n" + "\n\n".join(
                f"**{q['question']}**\n\n{answers[q['id']]['text']}" for q in QUESTIONS)
            requirements = next(s for s in data["sections"] if s["id"] == "requirements")
            requirements["body"] += decisions
            for item in requirements["items"]:
                key = {"new-REQ-2": "overdue", "new-REQ-5": "completed", "new-REQ-6": "editing"}.get(item["id"])
                if key:
                    item["statement"] = answers[key]["text"]
            evidence.append(source("Author's demo clarification answers", decisions, limit=40000))
        elif upstream.get("prd"):
            prd = upstream["prd"]
            context = next(s for s in data["sections"] if s["id"] == "context")
            context["body"] += f"\n\n## Selected published PRD v{prd['number']}\n\n" + "\n\n".join(
                f"**{s['title']}**\n\n{s['body']}\n\n" + "\n".join(f"- {i['id']}: {i['statement']} Check: {i['verification']}" for i in s['items'])
                for s in prd['sections'] if s['id'] in ('requirements', 'scope'))
            evidence.append(source(f"Selected published PRD v{prd['number']}", json.dumps(prd, ensure_ascii=False), limit=60000))
        else:
            next(s for s in data["sections"] if s["id"] == "context")["body"] += "\n\nThis standalone example uses the brief. No PRD or Design spec is selected; the behavioral rules above are proposals for review."
        for s in data["sections"]:
            s["source_ids"] = [evidence[0]["id"]]
        return Generation.model_validate(data), evidence, model
