from bili_chat.message_segments import segment_lengths, split_segments, validate_segments


def test_splits_non_empty_lines_and_counts_each_segment():
    text = "abc\n\n  \n" + "測" * 40

    assert split_segments(text) == ["abc", "測" * 40]
    assert segment_lengths(text) == [3, 40]
    assert validate_segments(split_segments(text)) == (True, None)


def test_rejects_the_first_segment_above_forty_characters():
    assert validate_segments(["ok", "測" * 41]) == (False, 2)
