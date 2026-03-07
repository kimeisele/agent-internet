import pytest

from agent_internet.steward_substrate import load_steward_substrate


pytest.importorskip("vibe_core")


def test_loads_canonical_substrate_symbols():
    bindings = load_steward_substrate()

    assert bindings.HEADER_SIZE_BYTES == 72
    assert bindings.NADI_BUFFER_SIZE == 144
    assert bindings.NadiOp.RECEIVE.value == "receive"
    assert bindings.NadiPriority.SUDDHA.value == 3
    assert bindings.FederationMessage.__name__ == "FederationMessage"
