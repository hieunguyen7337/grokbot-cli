#!/usr/bin/env python3
"""Phone notifications through ntfy for a repository's main Claude Code cloud session.

One stdlib-only file with no kit imports. `install` copies it into a repository as .claude/hooks/cloud-notify.py.

  cloud-notify hook                        Claude Code hook; reads the hook JSON on stdin, always exits 0
  cloud-notify push --title T --message M  send one message when USAGE_OPTIMIZER_NTFY_TOPIC is set
  cloud-notify mark-main [--dir D]         mark this cloud session as the repository's main session
  cloud-notify install --repo DIR          copy this file into DIR and register its hooks there

The hook sends only when all three hold: CLAUDE_CODE_REMOTE=true (a cloud session), the untracked marker
.claude/main-session exists in the project folder (only the main session creates it), and
USAGE_OPTIMIZER_NTFY_TOPIC is set (in the cloud environment's settings, never in git).
At most one message per event kind (stop, error, input) every 60 seconds; a new prompt starts those windows over.
Events from inside a subagent (a payload with agent_id) send nothing. The message names the event kind and the
repository only, never transcript, question or error text.
Other settings: USAGE_OPTIMIZER_NTFY_SERVER (default https://ntfy.sh), USAGE_OPTIMIZER_NOTIFY=off,
USAGE_OPTIMIZER_NOTIFY_DRY_RUN=1 (print the request, topic masked, instead of sending it) and
USAGE_OPTIMIZER_NOTIFY_DRY_RUN_FILE (append the dry-run requests to this file instead of stderr).
"""

import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

DEFAULT_SERVER = "https://ntfy.sh"
MARKER_REL = os.path.join(".claude", "main-session")
HOOK_REL = os.path.join(".claude", "hooks", "cloud-notify.py")
HOOK_MARK = ".claude/hooks/cloud-notify.py"
# The shell test keeps the hook a no-op outside the cloud, where `python3` can be a Windows Store stub.
# `|| true` keeps any failure from blocking a tool or a stop: python's usage error is exit 2, which blocks AskUserQuestion.
HOOK_COMMAND = '[ "$CLAUDE_CODE_REMOTE" != true ] || python3 "$CLAUDE_PROJECT_DIR/' + HOOK_MARK + '" hook || true'
# (event, matcher, async). UserPromptSubmit only resets the debounce, so it runs in line and stays ordered.
HOOK_EVENTS = (("Stop", None, True), ("StopFailure", None, True), ("Notification", None, True),
               ("PreToolUse", "AskUserQuestion", True), ("UserPromptSubmit", None, False))
HOOK_TIMEOUT = 15
POST_TIMEOUT = 10
DEBOUNCE_SECONDS = 60
MASK = "***"
TOPIC_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
SESSION_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
# Notification types that do not mean Claude is waiting on the user.
QUIET_NOTIFICATIONS = {"auth_success", "elicitation_complete", "elicitation_response", "quota_auto_resume_fired",
                       "agent_completed"}
# A background task of these types does not make a Stop "paused": monitors are long-lived watchers.
LONG_LIVED_TASKS = {"monitor"}
TITLES = {"stop": "finished", "input": "needs input", "error": "stopped with an error"}
TAGS = {"stop": "white_check_mark", "input": "question", "error": "warning"}
# The push body is a fixed line per event kind: the event kind and the repository name only, never message text.
BODIES = {"stop": "The turn ended; Claude is waiting for you.", "error": "The turn stopped on an API error.",
          "input": "Claude is waiting for your answer."}


class CloudNotifyError(Exception):
    pass


def ntfy_topic(env):
    topic = (env.get("USAGE_OPTIMIZER_NTFY_TOPIC") or "").strip()
    return topic if TOPIC_RE.match(topic) else None


def ntfy_server(env):
    server = (env.get("USAGE_OPTIMIZER_NTFY_SERVER") or "").strip().rstrip("/") or DEFAULT_SERVER
    return server if re.match(r"^https?://[^/\s?#]+(/[^\s?#]*)?$", server) else None


def notify_off(env):
    return (env.get("USAGE_OPTIMIZER_NOTIFY") or "").strip().lower() in ("off", "0", "false", "no")


def session_url(env):
    session = (env.get("CLAUDE_CODE_REMOTE_SESSION_ID") or "").strip()
    if not SESSION_RE.match(session):
        return None
    if session.startswith("cse_"):
        session = "session_" + session[len("cse_"):]
    return "https://claude.ai/code/" + session


def header_value(text):
    """A header value http.client can send: ASCII as is, anything else RFC 2047 encoded (ntfy decodes it)."""
    text = " ".join(str(text).split())
    try:
        text.encode("ascii")
        return text
    except UnicodeEncodeError:
        return "=?UTF-8?B?" + base64.b64encode(text.encode("utf-8")).decode("ascii") + "?="


def scrub(text, topic):
    text = str(text)
    return text.replace(topic, MASK) if topic else text


def build_request(env, title, message, tag=None):
    topic, server = ntfy_topic(env), ntfy_server(env)
    if not topic or not server:
        return None
    headers = {"Title": header_value(title), "Content-Type": "text/plain; charset=utf-8"}
    if tag:
        headers["Tags"] = tag
    click = session_url(env)
    if click:
        headers["Click"] = click
    return {"url": server + "/" + topic, "masked_url": server + "/" + MASK, "headers": headers,
            "body": str(message or "").encode("utf-8"), "topic": topic}


def default_sender(url, headers, body, timeout):
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        response.read(256)


def deliver(env, request, sender=None, stderr=None):
    """Send one request, or record it for a dry run. Returns True when it was sent or recorded."""
    stderr = stderr or sys.stderr
    if (env.get("USAGE_OPTIMIZER_NOTIFY_DRY_RUN") or "").strip() not in ("", "0"):
        record = json.dumps({"method": "POST", "url": request["masked_url"], "headers": request["headers"],
                             "body": request["body"].decode("utf-8")}, ensure_ascii=False)
        record = scrub(record, request["topic"])
        path = env.get("USAGE_OPTIMIZER_NOTIFY_DRY_RUN_FILE")
        if path:
            with open(path, "a", encoding="utf-8") as handle:
                handle.write(record + "\n")
        else:
            stderr.write("cloud-notify dry run: " + record + "\n")
        return True
    try:
        (sender or default_sender)(request["url"], dict(request["headers"]), request["body"], POST_TIMEOUT)
        return True
    except Exception as exc:  # A failed push must never stop the session; say why, without the topic.
        reason = scrub("{}: {}".format(type(exc).__name__, exc), request["topic"])
        stderr.write("cloud-notify: could not send to {}: {}\n".format(request["masked_url"], reason[:200]))
        return False


def project_dir(env, data=None):
    return env.get("CLAUDE_PROJECT_DIR") or (data or {}).get("cwd") or os.getcwd()


def is_main(project, env):
    """The marker exists and, when it names a cloud session, names this one."""
    path = os.path.join(project, MARKER_REL)
    if not os.path.isfile(path):
        return False
    try:
        with open(path, encoding="utf-8") as handle:
            owner = handle.readline().strip()
    except OSError:
        return False
    current = (env.get("CLAUDE_CODE_REMOTE_SESSION_ID") or "").strip()
    return not (owner and current and owner != current)


def state_path(env, data):
    base = env.get("USAGE_OPTIMIZER_NOTIFY_STATE_DIR") or os.path.join(
        tempfile.gettempdir(), "usage-optimizer-cloud-notify-{}".format(getattr(os, "getuid", lambda: "user")()))
    key = str(data.get("session_id") or env.get("CLAUDE_CODE_REMOTE_SESSION_ID") or "session")
    return os.path.join(base, hashlib.sha256(key.encode("utf-8")).hexdigest()[:24] + ".debounce")


def read_debounce(path):
    try:
        with open(path, encoding="utf-8") as handle:
            record = json.load(handle)
    except (OSError, ValueError):
        return {}
    return record if isinstance(record, dict) else {}


def claim_notify(path, kind, now):
    """At most one message per event kind every DEBOUNCE_SECONDS. Two different kinds in one turn both send, and a
    second prompt of the same kind sends once it is a minute past the first. A clock that went back starts over."""
    record = read_debounce(path)
    last = record.get(kind)
    if isinstance(last, (int, float)) and 0 <= now - last < DEBOUNCE_SECONDS:
        return False
    record[kind] = now
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    temp = "{}.{}.tmp".format(path, os.getpid())
    with open(os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w", encoding="utf-8") as handle:
        handle.write(json.dumps(record))
    os.replace(temp, path)
    return True


def reset_debounce(path):
    try:
        os.remove(path)
    except OSError:
        pass


def busy_in_background(data):
    tasks = data.get("background_tasks")
    if not isinstance(tasks, list):
        return False
    return any(not (isinstance(task, dict) and str(task.get("type", "")).lower() in LONG_LIVED_TASKS)
               for task in tasks)


def event_message(data):
    """The event kind ("stop", "error" or "input") for an event that should notify, else None. Carries no text."""
    event = data.get("hook_event_name")
    if event == "Stop":
        if busy_in_background(data):
            return None  # Not a wait: the session wakes itself when its background work ends.
        return "stop"
    if event == "StopFailure":
        return "error"
    if event == "Notification":
        if str(data.get("notification_type") or "") in QUIET_NOTIFICATIONS:
            return None
        return "input"
    if event == "PreToolUse" and data.get("tool_name") == "AskUserQuestion":
        return "input"
    return None


def run_hook(env, stdin, stderr, sender=None, clock=None):
    try:
        data = {} if stdin.isatty() else json.loads(stdin.read() or "{}")
    except (ValueError, OSError, AttributeError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    if notify_off(env) or env.get("CLAUDE_CODE_REMOTE") != "true":
        return 0
    if data.get("hook_event_name") == "UserPromptSubmit":
        reset_debounce(state_path(env, data))  # a new prompt starts a new turn, whose events are not held back
        return 0
    if str(data.get("agent_id") or "").strip():
        return 0  # an event from inside a subagent: only the main session's own events notify
    kind = event_message(data)
    project = project_dir(env, data)
    if not kind or not is_main(project, env) or not ntfy_topic(env):
        return 0
    repo = os.path.basename(os.path.normpath(project)) or "repository"
    request = build_request(env, "Claude: {} {}".format(repo, TITLES[kind]), BODIES[kind], TAGS[kind])
    if request and claim_notify(state_path(env, data), kind, (clock or time.time)()):
        deliver(env, request, sender, stderr)
    return 0


def run_push(args, env, stdout, stderr, sender=None):
    if notify_off(env):
        return 0
    request = build_request(env, args.title, args.message)
    if not request:
        if (env.get("USAGE_OPTIMIZER_NTFY_TOPIC") or "").strip():
            stderr.write("cloud-notify: USAGE_OPTIMIZER_NTFY_TOPIC or USAGE_OPTIMIZER_NTFY_SERVER is not valid; "
                         "nothing sent\n")
        return 0
    if deliver(env, request, sender, stderr):
        stdout.write("cloud-notify: sent\n")
    return 0


def git_ignores(repo, rel):
    git = shutil.which("git")
    if not git:
        return None
    try:
        result = subprocess.run([git, "-C", repo, "check-ignore", "-q", "--", rel.replace(os.sep, "/")],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return {0: True, 1: False}.get(result.returncode)


def default_mark_dir(env):
    if env.get("CLAUDE_PROJECT_DIR"):
        return env["CLAUDE_PROJECT_DIR"]
    here = os.path.dirname(os.path.abspath(__file__))
    if os.path.basename(here) == "hooks" and os.path.basename(os.path.dirname(here)) == ".claude":
        return os.path.dirname(os.path.dirname(here))  # the installed copy sits in <repo>/.claude/hooks/
    return os.getcwd()


def run_mark_main(args, env, stdout, stderr):
    project = os.path.abspath(args.dir or default_mark_dir(env))
    if not os.path.isdir(project):
        stderr.write("cloud-notify: not a folder: {}\n".format(project))
        return 1
    path = os.path.join(project, MARKER_REL)
    session = (env.get("CLAUDE_CODE_REMOTE_SESSION_ID") or "").strip()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write((session if SESSION_RE.match(session) else "") + "\n")
    except OSError as exc:
        stderr.write("cloud-notify: cannot write {}: {}\n".format(path, exc))
        return 1
    stdout.write("cloud-notify: marked this session as the main session ({})\n".format(path))
    if env.get("CLAUDE_CODE_REMOTE") != "true":
        stdout.write("note: this is not a cloud session (CLAUDE_CODE_REMOTE is not true), so the hook stays silent\n")
    if not ntfy_topic(env):
        stdout.write("note: USAGE_OPTIMIZER_NTFY_TOPIC is not set (or not a valid ntfy topic) in this environment, "
                     "so nothing is sent until it is\n")
    if git_ignores(project, MARKER_REL) is False:
        stdout.write("warning: git does not ignore .claude/main-session; add it to .gitignore and never commit it\n")
    settings = os.path.join(project, ".claude", "settings.json")
    try:
        with open(settings, encoding="utf-8") as handle:
            registered = HOOK_MARK in handle.read()
    except OSError:
        registered = False
    if not registered:
        stdout.write("warning: .claude/settings.json does not register the cloud-notify hook; run "
                     "`cloud-notify install --repo <dir>` from the kit\n")
    return 0


def wanted_hook(is_async):
    hook = {"type": "command", "command": HOOK_COMMAND, "timeout": HOOK_TIMEOUT}
    if is_async:
        hook["async"] = True
    return hook


def merge_settings(settings):
    """Add or update this tool's hook entries; keep every other setting and hook. Returns True on change."""
    if not isinstance(settings, dict):
        raise CloudNotifyError("settings.json does not hold a JSON object")
    hooks = settings.get("hooks", {})
    if not isinstance(hooks, dict):
        raise CloudNotifyError('"hooks" in settings.json is not an object')
    changed = "hooks" not in settings
    for event, matcher, is_async in HOOK_EVENTS:
        wanted = wanted_hook(is_async)
        groups = hooks.get(event, [])
        if not isinstance(groups, list):
            raise CloudNotifyError('"hooks.{}" in settings.json is not a list'.format(event))
        found = False
        for group in groups:
            entries = group.get("hooks") if isinstance(group, dict) else None
            for index, entry in enumerate(entries if isinstance(entries, list) else []):
                if isinstance(entry, dict) and HOOK_MARK in str(entry.get("command", "")):
                    found = True
                    if entry != wanted:
                        entries[index] = wanted
                        changed = True
                    if len(entries) == 1 and group.get("matcher") != matcher:
                        if matcher:
                            group["matcher"] = matcher
                        else:
                            group.pop("matcher", None)
                        changed = True
        if not found:
            group = {"matcher": matcher, "hooks": [wanted]} if matcher else {"hooks": [wanted]}
            groups.append(group)
            changed = True
        hooks[event] = groups
    settings["hooks"] = hooks
    return changed


def write_text(path, text):
    temp = "{}.{}.tmp".format(path, os.getpid())
    with open(temp, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    os.replace(temp, path)


def install_settings(repo):
    path = os.path.join(repo, ".claude", "settings.json")
    settings = {}
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as handle:
                text = handle.read()
            settings = json.loads(text) if text.strip() else {}
        except (OSError, ValueError) as exc:
            raise CloudNotifyError("cannot read {} as JSON ({}); fix it and run install again".format(path, exc))
    if not merge_settings(settings):
        return "already registers the hooks"
    write_text(path, json.dumps(settings, indent=2, ensure_ascii=False) + "\n")
    return "registered the hooks"


def install_gitignore(repo):
    path = os.path.join(repo, ".gitignore")
    try:
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
    except FileNotFoundError:
        text = ""
    if any(line.strip() in (".claude/main-session", "/.claude/main-session") for line in text.splitlines()):
        return "already ignores .claude/main-session"
    if text and not text.endswith("\n"):
        text += "\n"
    write_text(path, text + "# cloud-notify: marks this checkout's main cloud session; never commit it\n"
                            ".claude/main-session\n")
    return "now ignores .claude/main-session"


def install_copy(repo):
    source = os.path.abspath(__file__)
    target = os.path.join(repo, HOOK_REL)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(source, "rb") as handle:
        data = handle.read()
    if os.path.exists(target):
        with open(target, "rb") as handle:
            if handle.read() == data:
                return "already current"
    with open(target, "wb") as handle:
        handle.write(data)
    os.chmod(target, 0o755)
    return "copied"


CLAUDE_MD_SNIPPET = """\
### Cloud notifications (main session only)

If you are this repository's main cloud session (the user started you directly; your first message is not a lane
brief, so it has no "You are a worker dispatched by lane" or "CLOUD RUN" text), run this at the start of the
session, and again whenever `.claude/main-session` is missing:

    python3 .claude/hooks/cloud-notify.py mark-main

Worker sessions never run it. Never commit `.claude/main-session`, and never print USAGE_OPTIMIZER_NTFY_TOPIC.
"""

SETUP_STEPS = """\
1. Pick a long random ntfy topic (it is the password: anyone who knows it can read and send). Subscribe to it in
   the ntfy app (Android or iOS: + then the topic name) or at https://ntfy.sh/app (Subscribe to topic).
2. At claude.ai/code, open the environment selector under the message box, hover over the cloud environment the
   main session uses and select its settings icon. Under Environment variables add one line:
       USAGE_OPTIMIZER_NTFY_TOPIC=<your topic>
   Under Network access choose Custom, add ntfy.sh (or your own server) to Allowed domains and keep
   "Also include default list of common package managers" checked. Save changes.
   A running session picks the variable up the next time its VM restarts; a new session has it at once.
3. Commit .claude/settings.json, .claude/hooks/cloud-notify.py and .gitignore in this repository, and add the
   CLAUDE.md lines above to its orchestrator section.
4. Test from the main cloud session: python3 .claude/hooks/cloud-notify.py push --title Test --message Hello
"""


def run_install(args, stdout, stderr):
    repo = os.path.abspath(args.repo)
    if not os.path.isdir(repo):
        stderr.write("cloud-notify: not a folder: {}\n".format(repo))
        return 1
    try:
        os.makedirs(os.path.join(repo, ".claude"), exist_ok=True)
        steps = [(HOOK_REL, install_copy(repo)), (os.path.join(".claude", "settings.json"), install_settings(repo)),
                 (".gitignore", install_gitignore(repo))]
    except (CloudNotifyError, OSError) as exc:
        stderr.write("cloud-notify: {}\n".format(exc))
        return 1
    for rel, outcome in steps:
        stdout.write("cloud-notify: {}: {}\n".format(rel.replace(os.sep, "/"), outcome))
    for rel in (os.path.join(".claude", "settings.json"), HOOK_REL):
        if git_ignores(repo, rel):
            stdout.write("warning: git ignores {}; un-ignore it, or cloud sessions will not see the hook\n".format(
                rel.replace(os.sep, "/")))
    stdout.write("Nothing was committed. Add these lines to the repository's CLAUDE.md orchestrator section:\n\n")
    stdout.write(CLAUDE_MD_SNIPPET + "\nSetup steps:\n" + SETUP_STEPS)
    return 0


def parser():
    top = argparse.ArgumentParser(prog="cloud-notify", description=__doc__.split("\n\n")[0])
    commands = top.add_subparsers(dest="command", required=True)
    commands.add_parser("hook", help="run as a Claude Code hook (reads the hook JSON on stdin)")
    push = commands.add_parser("push", help="send one ntfy message if USAGE_OPTIMIZER_NTFY_TOPIC is set")
    push.add_argument("--title", required=True)
    push.add_argument("--message", required=True)
    mark = commands.add_parser("mark-main", help="mark this session as the repository's main cloud session")
    mark.add_argument("--dir", help="project folder (default: $CLAUDE_PROJECT_DIR, else the current folder)")
    install = commands.add_parser("install", help="copy this hook into a repository and register it")
    install.add_argument("--repo", required=True, help="the repository folder")
    return top


def main(argv=None, env=None, stdin=None, stdout=None, stderr=None, sender=None, clock=None):
    env = os.environ if env is None else env
    stdin, stdout, stderr = stdin or sys.stdin, stdout or sys.stdout, stderr or sys.stderr
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["hook"]:
        try:
            return run_hook(env, stdin, stderr, sender, clock)
        except Exception as exc:  # The hook never fails the session.
            stderr.write("cloud-notify: hook skipped: {}\n".format(scrub(type(exc).__name__, ntfy_topic(env))))
            return 0
    args = parser().parse_args(argv)
    if args.command == "push":
        return run_push(args, env, stdout, stderr, sender)
    if args.command == "mark-main":
        return run_mark_main(args, env, stdout, stderr)
    return run_install(args, stdout, stderr)


if __name__ == "__main__":
    sys.exit(main())
