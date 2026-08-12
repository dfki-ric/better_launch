"""Tests for _convert_launch_arg, which turns the argument strings ROS2 provides
into python values.

This is the inbound counterpart to test_ros2_parameter_convert.py, which covers
_value_to_yaml turning python values into the strings ROS2 carries.
"""

import sys
from unittest.mock import MagicMock

import pytest


# Mock ROS dependencies BEFORE importing better_launch
def mock_package(name):
    m = MagicMock()
    m.__path__ = []
    sys.modules[name] = m
    return m


mock_rclpy = mock_package("rclpy")
sys.modules["rclpy.node"] = MagicMock()
sys.modules["rclpy.logging"] = MagicMock()
sys.modules["rclpy.qos"] = MagicMock()
sys.modules["rclpy.task"] = MagicMock()
sys.modules["rclpy.executors"] = MagicMock()
sys.modules["rclpy.parameter"] = MagicMock()

mock_ament = mock_package("ament_index_python")
sys.modules["ament_index_python.packages"] = MagicMock()

mock_lifecycle_msgs = mock_package("lifecycle_msgs")
sys.modules["lifecycle_msgs.msg"] = MagicMock()
sys.modules["lifecycle_msgs.srv"] = MagicMock()

mock_launch = mock_package("launch")
sys.modules["launch.actions"] = MagicMock()
sys.modules["launch.launch_description_sources"] = MagicMock()

from better_launch.wrapper import _convert_launch_arg as convert


class TestBoolConversion:
    """ROS2 passes every argument as a string, so bools need explicit handling."""

    @pytest.mark.parametrize(
        "value",
        ["false", "False", "FALSE", "0", "no", "off", " false ", "  False"],
    )
    def test_falsy_spellings(self, value):
        assert convert(value, bool) is False

    @pytest.mark.parametrize(
        "value",
        ["true", "True", "TRUE", "1", "yes", "on", " true ", "  True"],
    )
    def test_truthy_spellings(self, value):
        assert convert(value, bool) is True

    def test_returns_actual_bools(self):
        """The result must be a real bool, not a truthy/falsy stand-in."""
        assert convert("false", bool) is False
        assert convert("true", bool) is True

    def test_already_a_bool_is_passed_through(self):
        assert convert(True, bool) is True
        assert convert(False, bool) is False

    @pytest.mark.parametrize("value", ["maybe", "", "2", "none", "flase"])
    def test_unrecognized_values_raise(self, value):
        """A typo must not quietly enable the flag."""
        with pytest.raises(ValueError, match="Cannot interpret"):
            convert(value, bool)


class TestNonBoolConversion:
    """Everything other than bool keeps the previous literal_eval behaviour."""

    @pytest.mark.parametrize(
        "value, ptype, expected",
        [
            ("42", int, 42),
            ("0", int, 0),
            ("-7", int, -7),
            ("3.14", float, 3.14),
            ("0.025", float, 0.025),
            ("hello", str, "hello"),
            ("RGGB", str, "RGGB"),
            ("[1, 2, 3]", list, [1, 2, 3]),
            ("{'a': 1}", dict, {"a": 1}),
        ],
    )
    def test_literal_values(self, value, ptype, expected):
        assert convert(value, ptype) == expected

    def test_unquoted_paths_stay_strings(self):
        """issue #11: a path without quotes is a SyntaxError for literal_eval."""
        assert convert("/tmp/some/path", str) == "/tmp/some/path"
        assert convert("/tmp/some path", str) == "/tmp/some path"

    def test_unknown_type_falls_back_to_literal_eval(self):
        """Args ROS2 supplies that the launch function never declared."""
        assert convert("42", None) == 42
        assert convert("hello", None) == "hello"
        # Without a declared type there is nothing to key bool handling off, so
        # this stays a string -- the pre-existing behaviour.
        assert convert("false", None) == "false"

    def test_bool_strings_are_untouched_without_a_bool_annotation(self):
        """A str-annotated arg that happens to read "false" stays a string."""
        assert convert("false", str) == "false"

    def test_literal_annotations(self):
        """Literal[...] args (see 'Added support for Literal launch args')."""
        from typing import Literal

        assert convert("right", Literal["left", "right"]) == "right"


class TestBoolRoundTrip:
    """A bool passed from one launch file to an included one must survive the trip. _value_to_yaml serializes it to "true"/"false" (see test_ros2_parameter_convert.py), which _convert_launch_arg has to turn back into the same bool."""

    @pytest.mark.parametrize("original", [True, False])
    def test_bool_survives_the_round_trip(self, original):
        on_the_wire = "true" if original else "false"
        assert convert(on_the_wire, bool) is original
