from bili_chat.text_conversion import to_simplified


def test_to_simplified_converts_traditional_words_and_keeps_other_text():
    assert to_simplified("繁體中文、電腦與網路 123!") == "繁体中文、电脑与网络 123!"
