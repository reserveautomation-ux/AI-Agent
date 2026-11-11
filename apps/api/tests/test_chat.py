"""Chat with your assistant: streaming replies, handing work to the workforce, memory."""

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from test_api import SECRET, SUPABASE_URL, auth
from workforce_api.config import Settings
from workforce_api.main import create_app


class Block(SimpleNamespace):
    def model_dump(self, exclude_none=False):
        return {k: v for k, v in vars(self).items() if not (exclude_none and v is None)}


def text_block(t):
    return Block(type="text", text=t)


def tool_block(name, args, id_="tu_1"):
    return Block(type="tool_use", id=id_, name=name, input=args)


def final(blocks, stop="end_turn"):
    usage = SimpleNamespace(input_tokens=1000, output_tokens=100)
    return SimpleNamespace(content=blocks, stop_reason=stop, model="claude-opus-5-5", usage=usage)


class FakeChat:
    """Scripted model: each call to run() plays the next round."""

    def __init__(self, *rounds):
        self.rounds = list(rounds)
        self.calls: list[dict] = []

    async def run(self, **params):
        self.calls.append(json.loads(json.dumps(params, default=str)))
        round_ = self.rounds.pop(0)
        if isinstance(round_, Exception):
            yield "text", "Partial ans"
            raise round_
        chunks, message = round_
        for c in chunks:
            yield "text", c
        yield "final", message


def say(*chunks):
    return list(chunks), final([text_block("".join(chunks))])


@pytest.fixture
def make_client(database_url):
    clients = []

    def make(model, **settings):
        s = Settings(
            database_url=database_url,
            supabase_url=SUPABASE_URL,
            supabase_jwt_secret=SECRET,
            **settings,
        )
        c = TestClient(create_app(s, chat_model=model))
        c.__enter__()
        clients.append(c)
        return c

    yield make
    for c in clients:
        c.__exit__(None, None, None)


def send(client, h, content, conversation_id=None, via="text"):
    body = {"content": content, "via": via}
    if conversation_id:
        body["conversation_id"] = conversation_id
    with client.stream("POST", "/chat", json=body, headers=h) as r:
        assert r.status_code == 200, r.read()
        assert r.headers["content-type"].startswith("text/event-stream")
        return [json.loads(line[6:]) for line in r.iter_lines() if line.startswith("data: ")]


def test_streams_a_reply_and_keeps_the_conversation(make_client, make_user, db):
    model = FakeChat(say("Namaste! ", "How can I help?"), say("Sure."))
    client = make_client(model)
    uid = make_user()
    h = auth(uid)

    events = send(client, h, "Hi there, I'm Asha from Pune")
    assert (
        events[0]["type"] == "conversation" and events[0]["title"] == "Hi there, I'm Asha from Pune"
    )
    assert [e["text"] for e in events if e["type"] == "text"] == ["Namaste! ", "How can I help?"]
    assert events[-1]["type"] == "done" and events[-1]["text"] == "Namaste! How can I help?"
    conv = events[0]["id"]

    # The model got the person's context and safe defaults.
    p = model.calls[0]
    assert p["messages"] == [{"role": "user", "content": "Hi there, I'm Asha from Pune"}]
    assert "You are AI Assistant, the personal AI assistant of owner@example.com" in p["system"]
    assert "Connected services: none yet" in p["system"] and "Gmail" in p["system"]
    assert p["thinking"] == {"type": "adaptive"} and p["output_config"] == {"effort": "low"}
    assert {t["name"] for t in p["tools"]} == {"start_task", "remember", "web_search"}

    send(client, h, "Thanks", conversation_id=conv)
    assert [m["role"] for m in model.calls[1]["messages"]] == ["user", "assistant", "user"]

    listed = client.get("/conversations", headers=h).json()
    assert [c["id"] for c in listed] == [conv]
    detail = client.get(f"/conversations/{conv}", headers=h).json()
    assert [(m["role"], m["content"]) for m in detail["messages"]] == [
        ("user", "Hi there, I'm Asha from Pune"),
        ("assistant", "Namaste! How can I help?"),
        ("user", "Thanks"),
        ("assistant", "Sure."),
    ]
    ws = client.get("/me", headers=h).json()["workspace"]["id"]
    assert (
        db.execute(
            "select count(*) from llm_calls where workspace_id = %s and purpose = 'chat'", (ws,)
        ).fetchone()[0]
        == 2
    )


def test_hands_real_work_to_the_workforce(make_client, make_user, db):
    objective = "Email rahul@example.com that the demo moves to Friday 4pm."
    model = FakeChat(
        (
            ["On it. "],
            final(
                [
                    text_block("On it. "),
                    tool_block("start_task", {"objective": objective, "title": "Email Rahul"}),
                ],
                stop="tool_use",
            ),
        ),
        say("I've asked the workforce; you'll approve the email before it goes."),
        say("It's waiting for your approval."),
    )
    client = make_client(model)
    h = auth(make_user())
    events = send(client, h, "Tell Rahul by email the demo moved to Friday 4pm")
    conv = events[0]["id"]
    task_event = next(e for e in events if e["type"] == "task")["task"]
    assert task_event["title"] == "Email Rahul" and task_event["status"] == "draft"
    assert events[-1]["text"].startswith("On it.\n\nI've asked the workforce")

    # The tool result went back to the model in the same turn.
    second = model.calls[1]["messages"]
    assert second[-2]["role"] == "assistant" and second[-2]["content"][-1]["type"] == "tool_use"
    assert json.loads(second[-1]["content"][0]["content"])["task_id"] == task_event["id"]

    row = db.execute(
        "select objective, conversation_id::text from tasks where id = %s", (task_event["id"],)
    ).fetchone()
    assert row == (objective, conv)

    # Worker progress shows up in the chat by itself.
    db.execute("update tasks set status = 'planned' where id = %s", (task_event["id"],))
    db.execute("update tasks set status = 'queued' where id = %s", (task_event["id"],))
    db.execute("update tasks set status = 'running' where id = %s", (task_event["id"],))
    db.execute(
        "update tasks set status = 'blocked', waiting_for_connection = '{gmail}',"
        " result_summary = 'To continue, connect Gmail in Connections.' where id = %s",
        (task_event["id"],),
    )
    detail = client.get(f"/conversations/{conv}", headers=h).json()
    update = detail["messages"][-1]
    assert update["role"] == "assistant" and update["meta"]["kind"] == "task_update"
    assert update["content"] == "To continue, connect Gmail in Connections."
    assert update["meta"]["waiting_for_connection"] == ["gmail"]
    assert detail["tasks"][task_event["id"]]["status"] == "blocked"
    assert detail["messages"][1]["meta"]["tasks"][0]["id"] == task_event["id"]

    # Next message: the assistant knows how the task is going.
    send(client, h, "How's it going?", conversation_id=conv)
    assert "- Email Rahul: blocked (To continue, connect Gmail" in model.calls[2]["system"]


def test_remembers_what_you_tell_it(make_client, make_user, db):
    model = FakeChat(
        (
            [],
            final(
                [tool_block("remember", {"content": "Asha is vegetarian", "kind": "preference"})],
                stop="tool_use",
            ),
        ),
        say("Noted, I'll remember that."),
        say("Here are some veg places."),
    )
    client = make_client(model)
    h = auth(make_user())
    events = send(client, h, "Remember I'm vegetarian")
    assert {"type": "memory", "content": "Asha is vegetarian"} in events
    ws = client.get("/me", headers=h).json()["workspace"]["id"]
    assert db.execute(
        "select memory_type, trusted from memories where workspace_id = %s", (ws,)
    ).fetchone() == ("preference", True)

    send(client, h, "Suggest dinner places for a vegetarian", via="voice")
    system = model.calls[2]["system"]
    assert "Asha is vegetarian" in system
    assert "talking to you by voice" in system


def test_memory_from_a_web_search_turn_is_not_trusted(make_client, make_user, db):
    model = FakeChat(
        (
            [],
            final(
                [
                    Block(type="server_tool_use", id="srv_1", name="web_search", input={}),
                    Block(type="web_search_tool_result", tool_use_id="srv_1", content=[]),
                    tool_block("remember", {"content": "Asha banks with X", "kind": "fact"}),
                ],
                stop="tool_use",
            ),
        ),
        say("Ok."),
    )
    client = make_client(model)
    h = auth(make_user())
    send(client, h, "look this up")
    ws = client.get("/me", headers=h).json()["workspace"]["id"]
    assert (
        db.execute("select trusted from memories where workspace_id = %s", (ws,)).fetchone()[0]
        is False
    )


def test_conversations_are_private(make_client, make_user):
    client = make_client(FakeChat(say("hi")))
    alice, bob = auth(make_user()), auth(make_user())
    conv = send(client, alice, "secret plans")[0]["id"]
    assert client.get(f"/conversations/{conv}", headers=bob).status_code == 404
    assert client.get("/conversations", headers=bob).json() == []
    r = client.post("/chat", json={"content": "x", "conversation_id": conv}, headers=bob)
    assert r.status_code == 404
    assert client.delete(f"/conversations/{conv}", headers=bob).status_code == 404
    # The owner can rename and delete it.
    r = client.post(f"/conversations/{conv}/rename", json={"title": "Plans"}, headers=alice)
    assert r.json()["title"] == "Plans"
    assert client.delete(f"/conversations/{conv}", headers=alice).status_code == 204
    assert client.get("/conversations", headers=alice).json() == []


def test_not_set_up_rate_limit_and_daily_cap(make_client, make_user):
    h = auth(make_user())
    r = make_client(None).post("/chat", json={"content": "hi"}, headers=h)
    assert r.status_code == 503 and "isn't set up" in r.text

    limited = make_client(FakeChat(say("a"), say("b")), chat_messages_per_minute=2)
    send(limited, h, "one")
    send(limited, h, "two")
    assert limited.post("/chat", json={"content": "three"}, headers=h).status_code == 429

    h2 = auth(make_user())
    capped = make_client(FakeChat(say("a")), chat_daily_budget_usd=0.001)
    send(capped, h2, "one")  # 1000 in + 100 out tokens on Opus is above $0.001
    r = capped.post("/chat", json={"content": "two"}, headers=h2)
    assert r.status_code == 429 and "chat limit" in r.text
    assert capped.post("/chat", json={"content": "   "}, headers=h2).status_code == 422


def test_emergency_stop_blocks_new_tasks_from_chat(make_client, make_user, db):
    model = FakeChat(
        ([], final([tool_block("start_task", {"objective": "x", "title": "x"})], stop="tool_use")),
        say("Everything is stopped right now."),
    )
    client = make_client(model)
    h = auth(make_user())
    ws = client.get("/me", headers=h).json()["workspace"]["id"]
    db.execute("update workspaces set kill_switch = true where id = %s", (ws,))
    events = send(client, h, "do x")
    result = model.calls[1]["messages"][-1]["content"][0]
    assert result["is_error"] and "Emergency stop" in result["content"]
    assert not any(e["type"] == "task" for e in events)
    assert (
        db.execute("select count(*) from tasks where workspace_id = %s", (ws,)).fetchone()[0] == 0
    )


def test_model_error_keeps_what_was_said(make_client, make_user):
    client = make_client(FakeChat(RuntimeError("boom")))
    h = auth(make_user())
    events = send(client, h, "hello")
    assert events[-1] == {
        "type": "error",
        "message": "Something went wrong while replying. Please try again.",
    }
    conv = events[0]["id"]
    last = client.get(f"/conversations/{conv}", headers=h).json()["messages"][-1]
    assert last["content"] == "Partial ans" and last["meta"]["interrupted"] is True


def test_name_your_assistant(make_client, make_user):
    model = FakeChat(say("Hi, I'm Maya."))
    client = make_client(model)
    h = auth(make_user())
    assert client.get("/me", headers=h).json()["assistant_name"] == "AI Assistant"
    r = client.post("/me/assistant", json={"name": "  Maya  "}, headers=h)
    assert r.status_code == 200 and r.json()["assistant_name"] == "Maya"
    send(client, h, "Who are you?")
    assert model.calls[0]["system"].startswith("You are Maya, the personal AI assistant")
    for bad in ("", "   ", "x" * 41, "<script>"):
        assert client.post("/me/assistant", json={"name": bad}, headers=h).status_code == 422
    # Each person names their own: someone else still has the default.
    assert client.get("/me", headers=auth(make_user())).json()["assistant_name"] == "AI Assistant"
