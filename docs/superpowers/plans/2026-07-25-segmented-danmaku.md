# Segmented Danmaku Sending Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enable deliberate multi-message danmaku submission with 40-character validation and safe randomized sending delays.

**Architecture:** A pure helper module parses the multiline editor into non-empty segments and validates their lengths. The UI shows its compact counts and forwards valid lists to `BiliClient`, which serially sends them in its existing asyncio loop.

**Tech Stack:** Python 3.11, CustomTkinter, asyncio, pytest.

## Global Constraints

- Every non-empty line is a user-chosen message with a maximum of 40 Python characters.
- Shift+Enter adds a line; Enter submits.
- A compact bottom status line renders counts as `32/40｜43/40｜18/40`, with over-limit counts red.
- The first message is immediate and later messages wait a randomized 1.5–3.0 seconds.
- Invalid batches are not partially sent; API failure stops remaining messages.

---

### Task 1: Add pure segmentation and validation

**Files:**

- Create: `bili_chat/message_segments.py`
- Create: `tests/test_message_segments.py`

**Interfaces:**

- `MAX_DANMAKU_LENGTH = 40`
- `split_segments(text: str) -> list[str]`
- `segment_lengths(text: str) -> list[int]`
- `validate_segments(segments: list[str]) -> tuple[bool, int | None]`

- [ ] **Step 1: Write the failing tests**

```python
from bili_chat.message_segments import segment_lengths, split_segments, validate_segments

def test_splits_non_empty_lines_and_counts_each_segment():
    text = "abc\n\n  \n" + "字" * 40
    assert split_segments(text) == ["abc", "字" * 40]
    assert segment_lengths(text) == [3, 40]
    assert validate_segments(split_segments(text)) == (True, None)

def test_rejects_the_first_segment_above_forty_characters():
    assert validate_segments(["ok", "字" * 41]) == (False, 2)
```

- [ ] **Step 2: Verify the expected failure**

Run `uv run pytest tests/test_message_segments.py -v`; it must fail because the module does not exist.

- [ ] **Step 3: Implement the minimum pure functions**

```python
MAX_DANMAKU_LENGTH = 40

def split_segments(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]

def segment_lengths(text: str) -> list[int]:
    return [len(segment) for segment in split_segments(text)]

def validate_segments(segments: list[str]) -> tuple[bool, int | None]:
    for index, segment in enumerate(segments, start=1):
        if len(segment) > MAX_DANMAKU_LENGTH:
            return False, index
    return True, None
```

- [ ] **Step 4: Verify green and commit**

Run `uv run pytest tests/test_message_segments.py -v`, then commit `bili_chat/message_segments.py` and `tests/test_message_segments.py` as `feat: validate segmented danmaku input`.

### Task 2: Replace the input editor and render counts

**Files:**

- Modify: `bili_chat/ui.py`
- Modify: `bili_chat/main.py`
- Test: `tests/test_message_segments.py`

**Interfaces:**

- `BiliChatUI` calls `on_send(segments: list[str])` only for a valid non-empty batch.
- `App.on_send` calls `BiliClient.send_messages(segments)`.

- [ ] **Step 1: Add the failing boundary test**

```python
from bili_chat.message_segments import validate_segments

def test_batch_is_not_valid_when_any_segment_exceeds_limit():
    assert validate_segments(["a" * 40, "b"]) == (True, None)
    assert validate_segments(["a", "b" * 41]) == (False, 2)
```

- [ ] **Step 2: Verify the test fails before the validation implementation exists**

Run `uv run pytest tests/test_message_segments.py -v` and confirm the missing-module failure.

- [ ] **Step 3: Implement the UI**

Replace `CTkEntry` with `CTkTextbox`; bind Shift+Return to insert a newline and Return to `_on_send_click` with `break`. On key release, derive counts from `segment_lengths`, render them joined with `｜`, colour counts red when above 40, and disable Send for empty or invalid text. Preserve valid text after a send attempt; clear only after forwarding the valid segment list.

- [ ] **Step 4: Verify green and commit**

Run `uv run pytest tests/test_message_segments.py -v`, then commit `bili_chat/ui.py`, `bili_chat/main.py`, and the test as `feat: show per-message danmaku counts`.

### Task 3: Implement serial client batch sending

**Files:**

- Modify: `bili_chat/bili_client.py`
- Create: `tests/test_bili_client.py`

**Interfaces:**

- `BiliClient.send_messages(segments: list[str]) -> None`
- `BiliClient._send_danmaku_batch(segments: list[str]) -> Coroutine[Any, Any, bool]`

- [ ] **Step 1: Write the failing order-and-delay test**

```python
import pytest
from bili_chat.bili_client import BiliClient

@pytest.mark.asyncio
async def test_sends_in_order_and_only_waits_between_messages(monkeypatch):
    client, sent, waits = BiliClient(), [], []
    async def fake_send(text):
        sent.append(text)
        return True
    async def fake_sleep(seconds):
        waits.append(seconds)
    monkeypatch.setattr(client, "_send_danmaku", fake_send)
    monkeypatch.setattr("bili_chat.bili_client.asyncio.sleep", fake_sleep)
    monkeypatch.setattr("bili_chat.bili_client.random.uniform", lambda low, high: 2.0)
    assert await client._send_danmaku_batch(["one", "two", "three"])
    assert sent == ["one", "two", "three"]
    assert waits == [2.0, 2.0]
```

- [ ] **Step 2: Verify red**

Run `uv run pytest tests/test_bili_client.py -v`; it must fail because `_send_danmaku_batch` is absent.

- [ ] **Step 3: Implement minimum serial send behavior**

Import `random` and `validate_segments`; reject invalid lists before scheduling. Send each segment in order, use `await asyncio.sleep(random.uniform(1.5, 3.0))` before each segment after the first, and log batch index. Return false and stop on the first failed `_send_danmaku` call.

- [ ] **Step 4: Add the failure-stop test and verify green**

```python
@pytest.mark.asyncio
async def test_stops_after_a_failed_segment(monkeypatch):
    client, sent = BiliClient(), []
    async def fake_send(text):
        sent.append(text)
        return text != "fail"
    monkeypatch.setattr(client, "_send_danmaku", fake_send)
    assert not await client._send_danmaku_batch(["first", "fail", "never"])
    assert sent == ["first", "fail"]
```

Run `uv run pytest tests/test_bili_client.py -v`, then commit with `feat: send danmaku batches sequentially`.

### Task 4: Complete verification

**Files:** Verify all modified production and test files.

- [ ] **Step 1: Run automated verification**

Run `uv run pytest -v` and `uv run python -m compileall bili_chat`; both must exit successfully.

- [ ] **Step 2: Manually smoke-test the GUI**

Run `uv run python run.pyw`. Confirm Shift+Enter creates multiple counts, over-limit text renders red and disables Send, and valid Enter submission starts the batch.

- [ ] **Step 3: Commit final corrections if any**

Run `git add bili_chat tests` then `git commit -m "test: verify segmented danmaku sending"` only if the verification work changed tracked files.
