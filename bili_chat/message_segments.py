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
