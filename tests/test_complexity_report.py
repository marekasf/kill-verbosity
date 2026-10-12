from killverbosity import complexity


def test_ari_on_a_fixed_text():
    text = "The cat sat on the mat. It was happy.\n\n- Run it now\n\n```\nx=1.\n```\nSee `code` and http://a.b/c here."
    assert round(complexity.measure(text)[0], 3) == -5.425


def test_mtld_on_a_repeated_word():
    assert complexity.measure("the the the the.")[1] == 2.0
