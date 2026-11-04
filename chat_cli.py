#!/usr/bin/env python3
"""Log in and send chat requests to a running MindBridge API from the terminal."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")


def request_json(url: str, payload: dict, token: str | None = None) -> dict:
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(url, data=json.dumps(payload).encode(), headers=headers, method="POST")
    try:
        with urlopen(req, timeout=120) as response:
            body = response.read().decode("utf-8")
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            detail = json.dumps(json.loads(body), indent=2)
        except json.JSONDecodeError:
            detail = body
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"Could not reach {url}: {exc}") from exc
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"API returned non-JSON data: {body[:500]}") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", choices=("patient", "doctor", "caretaker"), default="patient")
    parser.add_argument("--base-url", default=os.getenv("CHAT_API_URL", "http://127.0.0.1:5001"),
                        help="API origin (default: CHAT_API_URL or http://127.0.0.1:5001)")
    parser.add_argument("--username", default=os.getenv("CHAT_USERNAME"), help="login username")
    parser.add_argument("--patient-id", type=int, help="required for doctor/caretaker chat")
    parser.add_argument("--query", help="send one message; omit for interactive mode")
    parser.add_argument("--token", default=os.getenv("CHAT_TOKEN"),
                        help="reuse a JWT instead of logging in (or set CHAT_TOKEN)")
    args = parser.parse_args()

    if args.role in ("doctor", "caretaker") and args.patient_id is None:
        parser.error("--patient-id is required for doctor and caretaker roles")

    base = args.base_url.rstrip("/")
    token = args.token
    try:
        if not token:
            username = args.username or input("Username: ").strip()
            password = getpass.getpass("Password: ")
            login = request_json(f"{base}/api/auth/login/{args.role}",
                                 {"username": username, "password": password})
            token = login["token"]

        endpoint = "/api/patient/chat" if args.role == "patient" else "/api/staff/chat"

        def send(query: str) -> bool:
            payload = {"query": query}
            if args.role != "patient":
                payload["patient_id"] = args.patient_id
            result = request_json(f"{base}{endpoint}", payload, token)
            print(json.dumps(result, indent=2, ensure_ascii=False))
            return True

        if args.query is not None:
            send(args.query)
            return 0

        print("Interactive chat. Enter /quit to exit.")
        while True:
            try:
                query = input("you> ").strip()
            except EOFError:
                print()
                break
            if query.lower() in {"/quit", "/exit"}:
                break
            if query:
                send(query)
        return 0
    except (RuntimeError, KeyError) as exc:
        print(f"chat_cli: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
