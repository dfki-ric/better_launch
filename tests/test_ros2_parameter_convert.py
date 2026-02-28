import pytest
import json
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

if TYPE_CHECKING:
    from better_launch.launcher import BetterLaunch


class TestParameterTranslation:
    @pytest.mark.parametrize("input_val, expected_output", [
        (True, "true"),
        (False, "false"),
        (42, "42"),
        (3.14, "3.14"),
        ("hello", "hello"),
        ("true", "true"), # String "true" should stay "true"
        ([1, 2, 3], "[1, 2, 3]"),
        ({"a": 1, "b": 2}, '{"a": 1, "b": 2}'),
        (None, ""),
    ])
    def test_value_to_yaml(
        self, bl: "BetterLaunch", input_val, expected_output
    ) -> None:
        """Test that _value_to_yaml correctly converts Python types to ROS2-compatible YAML strings."""
        assert bl._value_to_yaml(input_val) == expected_output

    def test_complex_nested_structure(self, bl: "BetterLaunch") -> None:
        """Test nested structures."""
        data = {"list": [1, 2], "bool": True, "nested": {"x": "y"}}
        # JSON serialization order might vary, but for this simple case it's usually stable.
        # However, to be safe, we can parse the output back and compare.
        output = bl._value_to_yaml(data)
        assert json.loads(output) == data

    def test_string_quoting(self, bl: "BetterLaunch") -> None:
        """Test that strings are NOT quoted (passed as-is)."""
        # ROS2 launch arguments are typically just strings.
        # If we pass "foo", it receives "foo".
        # If we pass '"foo"', it receives '"foo"'.
        assert bl._value_to_yaml("foo") == "foo"
        assert bl._value_to_yaml("foo bar") == "foo bar"

    def test_non_serializable(self, bl: "BetterLaunch") -> None:
        """Test that non-serializable types raise ValueError."""
        class CustomObj:
            pass
        
        with pytest.raises(ValueError, match="Failed to serialize launch argument"):
            bl._value_to_yaml(CustomObj())

    def test_substitutions_passed_through(self, bl: "BetterLaunch") -> None:
        """Test that ROS2 Substitution objects are passed through unchanged."""
        # Create a dummy object that looks like a Substitution (duck typing)
        class MockSubstitution:
            def perform(self, context):
                return "substituted"
        
        sub = MockSubstitution()
        assert bl._value_to_yaml(sub) is sub

    def test_none_behavior(self, bl: "BetterLaunch") -> None:
        """Test that None returns an empty string."""
        assert bl._value_to_yaml(None) == ""

    def test_pre_serialized_yaml(self, bl: "BetterLaunch") -> None:
        """Test that strings looking like YAML/JSON are passed as-is."""
        # If the user manually serialized it, we shouldn't double-encode it
        yaml_str = "[1, 2, 3]"
        assert bl._value_to_yaml(yaml_str) == yaml_str
        
        json_str = '{"a": 1}'
        assert bl._value_to_yaml(json_str) == json_str

    def test_mixed_types_in_include(self, better_launch_cls):
        """Test mixing primitive types and substitutions in include."""
        bl = better_launch_cls()
        bl.ros2_actions = MagicMock()
        bl.find = MagicMock(return_value="/dummy/path.launch.py")
        
        class MockSubstitution:
            def perform(self, context): return "val"
            
        sub = MockSubstitution()
        
        bl._include_ros2_launchfile(
            "/dummy/path.launch.py", 
            arg1=True, 
            arg2=sub,
            arg3="string"
        )
        
        # Verify call args
        from launch.actions import IncludeLaunchDescription
        _, kwargs = IncludeLaunchDescription.call_args
        launch_args = dict(kwargs.get("launch_arguments"))
        
        assert launch_args["arg1"] == "true"
        assert launch_args["arg2"] is sub
        assert launch_args["arg3"] == "string"

    def test_special_floats(self, bl: "BetterLaunch") -> None:
        """Test handling of NaN and Infinity."""
        assert bl._value_to_yaml(float("nan")) == ".NaN"
        assert bl._value_to_yaml(float("inf")) == ".inf"
        assert bl._value_to_yaml(float("-inf")) == "-.inf"
        assert bl._value_to_yaml(3.14) == "3.14"

    def test_empty_containers(self, bl: "BetterLaunch") -> None:
        """Test empty lists and dicts."""
        assert bl._value_to_yaml([]) == "[]"
        assert bl._value_to_yaml({}) == "{}"

    def test_describe_only_substitution(self, bl: "BetterLaunch") -> None:
        """Test a substitution that only has describe() (duck typing)."""
        class DescribeOnlySub:
            def describe(self): return "description"
            
        sub = DescribeOnlySub()
        assert bl._value_to_yaml(sub) is sub
