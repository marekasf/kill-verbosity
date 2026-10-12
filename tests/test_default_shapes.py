def test_ste_grammar_shapes_are_on_by_default(kv):
    kinds = {h[1] for h in kv.find_shapes([
        "The valve is closed by the operator; the pump stops."])}
    assert {"semicolon", "passive voice"} <= kinds
