#!/usr/bin/env python3
"""Unit tests for click utilities, specifically parse_node_params."""

import pytest
from better_launch.utils.click import parse_node_params


class TestParseNodeParams:
    """Tests for parse_node_params function."""

    def test_empty_kwargs(self):
        """Empty kwargs should return empty results."""
        remaining, node_params = parse_node_params({})
        assert remaining == {}
        assert node_params == {}

    def test_no_node_params(self):
        """Kwargs without dot notation should be returned as remaining."""
        kwargs = {"verbose": True, "count": 5}
        remaining, node_params = parse_node_params(kwargs)
        assert remaining == {"verbose": True, "count": 5}
        assert node_params == {}

    def test_single_node_param(self):
        """Single node.param should be extracted."""
        kwargs = {"my_node.rate": 10}
        remaining, node_params = parse_node_params(kwargs)
        assert remaining == {}
        assert node_params == {"my_node": {"rate": 10}}

    def test_multiple_params_same_node(self):
        """Multiple params for same node should be grouped."""
        kwargs = {"talker.rate": 10, "talker.enabled": True}
        remaining, node_params = parse_node_params(kwargs)
        assert remaining == {}
        assert node_params == {"talker": {"rate": 10, "enabled": True}}

    def test_multiple_nodes(self):
        """Params for different nodes should be separated."""
        kwargs = {"talker.rate": 10, "listener.buffer_size": 100}
        remaining, node_params = parse_node_params(kwargs)
        assert remaining == {}
        assert node_params == {
            "talker": {"rate": 10},
            "listener": {"buffer_size": 100},
        }

    def test_mixed_kwargs(self):
        """Node params mixed with regular kwargs."""
        kwargs = {"verbose": True, "my_node.rate": 10, "debug": False}
        remaining, node_params = parse_node_params(kwargs)
        assert remaining == {"verbose": True, "debug": False}
        assert node_params == {"my_node": {"rate": 10}}

    def test_string_value(self):
        """String values should remain as strings."""
        kwargs = {"node.name": "hello_world"}
        remaining, node_params = parse_node_params(kwargs)
        assert remaining == {}
        assert node_params == {"node": {"name": "hello_world"}}

    def test_float_value(self):
        """Float values should be preserved."""
        kwargs = {"node.rate": 0.5}
        remaining, node_params = parse_node_params(kwargs)
        assert remaining == {}
        assert node_params == {"node": {"rate": 0.5}}

    def test_boolean_values(self):
        """Boolean values should be preserved."""
        kwargs = {"node.enabled": True, "node.debug": False}
        remaining, node_params = parse_node_params(kwargs)
        assert remaining == {}
        assert node_params == {"node": {"enabled": True, "debug": False}}

    def test_list_value(self):
        """List values should be preserved."""
        kwargs = {"node.items": [1, 2, 3]}
        remaining, node_params = parse_node_params(kwargs)
        assert remaining == {}
        assert node_params == {"node": {"items": [1, 2, 3]}}

    def test_dict_value(self):
        """Dict values should be preserved."""
        kwargs = {"node.config": {"key": "value"}}
        remaining, node_params = parse_node_params(kwargs)
        assert remaining == {}
        assert node_params == {"node": {"config": {"key": "value"}}}

    def test_nested_param_name(self):
        """Param names with dots should work (split on first dot only)."""
        kwargs = {"node.nested.param": 42}
        remaining, node_params = parse_node_params(kwargs)
        assert remaining == {}
        assert node_params == {"node": {"nested.param": 42}}


if __name__ == "__main__":
    pytest.main(["-v", __file__])
