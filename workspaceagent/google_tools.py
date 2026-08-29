from datetime import datetime, timedelta, timezone

import requests


GMAIL_URL = "https://gmail.googleapis.com/gmail/v1/users/me"
CALENDAR_URL = "https://www.googleapis.com/calendar/v3/calendars/primary/events"


class GoogleToolError(Exception):
    pass


class GoogleWorkspace:
    def __init__(self, access_token):
        self.headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}

    def _request(self, method, url, **kwargs):
        response = requests.request(method, url, headers=self.headers, timeout=(10, 45), **kwargs)
        if not response.ok:
            if response.status_code in (401, 403):
                raise GoogleToolError("Google denied this action. Reconnect your account and verify permissions.")
            raise GoogleToolError(f"Google service request failed with status {response.status_code}")
        return response.json() if response.content else None

    def search_mail(self, query="newer_than:14d", max_results=10):
        result = self._request("GET", f"{GMAIL_URL}/messages", params={"q": query, "maxResults": min(max_results, 20)})
        messages = []
        for item in result.get("messages", []):
            message = self._request(
                "GET", f"{GMAIL_URL}/messages/{item['id']}",
                params={"format": "metadata", "metadataHeaders": ["From", "Subject", "Date"]},
            )
            headers = {header["name"].lower(): header["value"] for header in message.get("payload", {}).get("headers", [])}
            messages.append({
                "id": item["id"], "thread_id": message.get("threadId"),
                "from": headers.get("from", "Unknown sender"), "subject": headers.get("subject", "(no subject)"),
                "date": headers.get("date", ""), "snippet": message.get("snippet", ""),
                "important": "IMPORTANT" in message.get("labelIds", []),
            })
        return messages

    def list_events(self, time_min=None, time_max=None, query=None, max_results=20):
        now = datetime.now(timezone.utc)
        params = {
            "singleEvents": "true", "orderBy": "startTime", "maxResults": min(max_results, 50),
            "timeMin": time_min or now.isoformat(),
            "timeMax": time_max or (now + timedelta(days=30)).isoformat(),
        }
        if query:
            params["q"] = query
        result = self._request("GET", CALENDAR_URL, params=params)
        return [{
            "id": event["id"], "summary": event.get("summary", "Untitled event"),
            "start": event.get("start", {}).get("dateTime") or event.get("start", {}).get("date"),
            "end": event.get("end", {}).get("dateTime") or event.get("end", {}).get("date"),
            "location": event.get("location"), "description": event.get("description"),
            "html_link": event.get("htmlLink"),
        } for event in result.get("items", [])]

    def create_event(self, summary, start, end, timezone_name=None, description=None, location=None, attendees=None):
        start_value = {"dateTime": start}
        end_value = {"dateTime": end}
        if timezone_name:
            start_value["timeZone"] = timezone_name
            end_value["timeZone"] = timezone_name
        body = {"summary": summary, "start": start_value, "end": end_value}
        if description:
            body["description"] = description
        if location:
            body["location"] = location
        if attendees:
            body["attendees"] = [{"email": email} for email in attendees]
        return self._request("POST", CALENDAR_URL, params={"sendUpdates": "all"}, json=body)

    def delete_event(self, event_id):
        self._request("DELETE", f"{CALENDAR_URL}/{event_id}", params={"sendUpdates": "all"})
        return {"deleted": True, "event_id": event_id}
