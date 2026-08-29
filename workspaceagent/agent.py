import json
from datetime import datetime, timezone

from .providers import text_response, tool_plan


READ_ACTIONS = {"gmail_search", "gmail_important", "calendar_list"}
WRITE_ACTIONS = {"calendar_create", "calendar_delete"}
ALL_ACTIONS = READ_ACTIONS | WRITE_ACTIONS | {"answer"}


def _parse_plan(raw):
    try:
        plan = json.loads(raw.strip().removeprefix("```json").removesuffix("```").strip())
    except json.JSONDecodeError as error:
        raise ValueError("The model could not create a valid workspace action") from error
    if plan.get("action") not in ALL_ACTIONS or not isinstance(plan.get("arguments", {}), dict):
        raise ValueError("The model selected an unsupported workspace action")
    return plan


def _planning_prompt():
    return (
        f"You are a Gmail and Google Calendar agent. Current UTC time: {datetime.now(timezone.utc).isoformat()}. "
        "Use a provided function whenever the request needs Google data or a calendar change. "
        "Never invent email, event, attendee, or date data. Calendar changes are reviewed by the app before execution."
    )


def run_agent(message, history, provider, api_key, model, google, llm=None):
    trace = [{"step": "understand", "status": "complete", "detail": "Interpreted the request"}]
    plan = _parse_plan(llm(provider, api_key, model, [{"role": "user", "content": message}])) if llm else tool_plan(
        provider, api_key, model, _planning_prompt(), message, history
    )
    action = plan["action"]
    arguments = plan.get("arguments", {})
    trace.append({"step": "plan", "status": "complete", "detail": f"Selected {action}", "arguments": arguments})

    if action == "calendar_delete" and not arguments.get("event_id"):
        trace.append({"step": "google", "status": "running", "detail": "Finding the calendar event before requesting approval"})
        matches = google.list_events(**{
            key: arguments[key] for key in ("time_min", "time_max", "query") if arguments.get(key)
        })
        trace[-1].update({"status": "complete", "detail": f"Found {len(matches)} matching events"})
        if len(matches) != 1:
            message = "I could not find that calendar event." if not matches else "I found multiple matching events. Please include the meeting date or time."
            return {"status": "complete", "message": message, "data": matches, "trace": trace}
        arguments = {"event_id": matches[0]["id"], "summary": matches[0]["summary"], "start": matches[0]["start"]}

    if action in WRITE_ACTIONS:
        trace.append({"step": "confirmation", "status": "waiting", "detail": "Waiting for your approval before changing Google Calendar"})
        return {
            "status": "confirmation_required", "message": plan.get("explanation") or "Confirm this calendar change.",
            "pending_action": {"action": action, "arguments": arguments}, "trace": trace,
        }
    if action == "answer":
        return {"status": "complete", "message": arguments.get("response", plan.get("explanation", "How can I help?")), "trace": trace}

    trace.append({"step": "google", "status": "running", "detail": f"Calling {action}"})
    if action == "gmail_search":
        result = google.search_mail(arguments.get("query", "newer_than:14d"), arguments.get("max_results", 10))
    elif action == "gmail_important":
        result = google.search_mail(arguments.get("query", "is:important newer_than:30d"), arguments.get("max_results", 10))
    else:
        result = google.list_events(**{key: value for key, value in arguments.items() if value is not None})
    trace[-1].update({"status": "complete", "detail": f"Google returned {len(result)} items"})

    grounded_prompt = (
        "Answer the user's request using only this Google tool result. Be concise, preserve dates and senders, "
        "and say clearly when no items were found.\n"
        f"USER REQUEST: {message}\nTOOL RESULT: {json.dumps(result, ensure_ascii=True)}"
    )
    context = [{"role": item["role"], "content": item["content"]} for item in history[-6:]]
    context.append({"role": "user", "content": grounded_prompt})
    answer = llm(provider, api_key, model, context) if llm else text_response(provider, api_key, model, context)
    trace.append({"step": "answer", "status": "complete", "detail": "Generated an answer grounded in Google data"})
    return {"status": "complete", "message": answer, "data": result, "trace": trace}


def execute_confirmed(action, google):
    name = action["action"]
    arguments = action["arguments"]
    if name == "calendar_create":
        result = google.create_event(**{key: value for key, value in arguments.items() if value is not None})
        return "The calendar event was created.", result
    if name == "calendar_delete":
        result = google.delete_event(arguments["event_id"])
        return f"{arguments.get('summary', 'The calendar event')} was removed.", result
    raise ValueError("This workspace action cannot be confirmed")
