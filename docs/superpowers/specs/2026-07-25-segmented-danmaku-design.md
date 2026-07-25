# Segmented Danmaku Sending Design

## Goal

Prevent messages that exceed Bilibili's 40-character limit from reaching the API, while letting the user deliberately send several short messages from one input area.

## Interaction

- Replace the current single-line input with a multiline text box.
- `Shift+Enter` inserts a newline. Each non-empty line is one message segment.
- `Enter` sends the batch. The UI prevents the text box's default newline insertion for this shortcut.
- A compact status line below the input shows the character count for each non-empty segment, for example `32/40｜43/40｜18/40`.
- Counts at or below 40 use the normal muted colour. Counts above 40 use red.
- The Send button is disabled whenever there is no non-whitespace message or any segment exceeds 40 characters.

## Validation and Sending

- UI validation is immediate, but the application layer also validates every segment before scheduling sends.
- Empty or whitespace-only lines are ignored.
- If a segment is over 40 characters, the whole batch is rejected; no partial sends occur.
- Valid segments are sent in their original order.
- A randomized, reasonable delay is inserted between consecutive messages to lower the risk of a rate-limit response. The delay is 1.5 to 3.0 seconds; the first message is sent immediately.
- The log reports batch progress. If one API call fails, the remaining queued messages are not sent and the log states which message failed.

## Architecture

`BiliChatUI` owns text entry, per-line counting, keyboard shortcuts, and enabled-state rendering. `App` passes a list of validated user-intended segments to `BiliClient`. `BiliClient` owns asynchronous sequential sending, revalidates the limit, waits between messages without blocking the UI thread, and logs outcomes through the existing message queue.

## Testing

- Extract pure message-segmentation and validation helpers so they can be tested without creating a GUI.
- Test line splitting, empty-line removal, length boundary values, and an over-limit batch rejection.
- Test the client sends messages in order, waits only between messages, and stops after a failure by injecting a sender and delay provider in tests.
