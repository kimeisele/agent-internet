from agent_internet.steward_protocol_compat import load_steward_protocol_bindings


def test_steward_protocol_bindings_expose_route_primitives():
    bindings = load_steward_protocol_bindings()

    assert bindings.default_route_nadi_type == "vyana"
    assert bindings.default_route_priority == "rajas"
    assert bindings.default_timeout_ms > 0
    assert "vyana" in bindings.allowed_nadi_types
    assert "rajas" in bindings.allowed_priorities

