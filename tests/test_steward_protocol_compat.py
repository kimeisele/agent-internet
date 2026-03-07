from agent_internet.steward_protocol_compat import load_steward_protocol_bindings, resolve_nadi_message_semantics


def test_steward_protocol_bindings_expose_route_primitives():
    bindings = load_steward_protocol_bindings()

    assert bindings.default_message_nadi_op == "send"
    assert bindings.default_message_nadi_type == "vyana"
    assert bindings.default_message_priority == "rajas"
    assert bindings.default_route_nadi_type == "vyana"
    assert bindings.default_route_priority == "rajas"
    assert bindings.default_timeout_ms > 0
    assert "send" in bindings.allowed_nadi_ops
    assert "vyana" in bindings.allowed_nadi_types
    assert "rajas" in bindings.allowed_priorities


def test_resolve_nadi_message_semantics_uses_steward_defaults():
    semantics = resolve_nadi_message_semantics()

    assert semantics.nadi_op == "send"
    assert semantics.nadi_type == "vyana"
    assert semantics.priority == "rajas"
    assert semantics.ttl_ms > 0

