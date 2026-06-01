#!/usr/bin/env python3
import pytest
import time
from pathlib import Path
from concurrent.futures import Future

from better_launch import BetterLaunch
from better_launch.elements import Node

from launch_ros.actions import Node as RosLaunchNode
from rclpy.qos import qos_profile_parameters


# Run tests via `colcon test --packages-select better_launch`.
# Examine results with `colcon test-result --all`


@pytest.fixture(scope="session")
def some_function_name():
    # Do any setup stuff before the tests start
    yield

    # Once we're done make sure to tear down everything
    bl = BetterLaunch.instance()
    if bl:
        bl.shutdown()
        nodes = bl.get_nodes(include_components=True)
        still_alive = [not n.is_running for n in nodes]
        assert all(still_alive), (
            f"The following nodes refused to shutdown: {still_alive}"
        )


@pytest.fixture(autouse=True)
def test_setup():
    yield
    # Allow some time to pass for ROS to clean up topics and such
    time.sleep(2.0)


def _assert_talker_listener_running(talker: Node, listener: Node, topic: str) -> bool:
    """Verify the given talker and listener are running and using the given topic."""
    time.sleep(5.0)

    bl = BetterLaunch()

    # Verify talker and listener are alive
    alive_nodes = bl.shared_node.get_node_names()
    assert talker.name in alive_nodes, (
        f"Talker {talker.name} not listed, alive nodes: {alive_nodes}"
    )
    assert listener.name in alive_nodes, (
        f"Listener {listener.name} not listed, alive nodes: {alive_nodes}"
    )

    assert talker.is_running, f"Talker {talker.name} not running"
    assert listener.is_running, f"Listener {listener.name} not running"

    # Check correct topic is published/subscribed
    assert topic in talker.get_published_topics(), (
        "Talker is not publishing on expected topic"
    )
    assert topic in listener.get_subscribed_topics(), (
        "Listener is not subscribed on expected topic"
    )

    # Shutdown talker and listener
    talker.shutdown("Test successful", timeout=10.0)
    assert not talker.is_running, "Talker failed to shutdown"

    listener.shutdown("Test successful", timeout=10.0)
    assert not listener.is_running, "Listener failed to shutdown"

    alive_nodes = bl.shared_node.get_node_names()
    assert talker.name not in alive_nodes, f"Talker {talker.name} is still alive"
    assert listener.name not in alive_nodes, f"Listener {listener.name} is still alive"


def test_bl_init():
    """Test basic initialization"""
    bl = BetterLaunch()
    assert bl is not None, "BetterLaunch initialized"

    this_file = bl.find(filename=Path(__file__).name, subdir="../**")
    assert Path(bl.launchfile) == Path(this_file), "Could not locate test file"

    assert bl.shared_node.count_publishers("rosout") >= 1, "Shared node not working"


def test_topic():
    """Test the publish/subscribe helpers."""
    bl = BetterLaunch()
    message_future = Future()

    def on_msg(msg):
        message_future.set_result(msg)

    msg_type = bl.get_ros_message_type("std_msgs/msg/String")
    sub = bl.subscriber(
        "/test/better_launch/topic_test",
        msg_type,
        callback=on_msg,
        qos_profile=qos_profile_parameters,
    )

    time.sleep(1.0)

    bl.publish_message(
        "/test/better_launch/topic_test",
        msg_type,
        {"data": "hello world"},
        qos_profile=qos_profile_parameters,
    )

    result = message_future.result(2.0).data
    assert result == "hello world", "Failed to receive message"
    sub.destroy()


def test_node():
    """Verify running regular nodes works."""
    bl = BetterLaunch()

    talker = bl.node(
        "examples_rclpy_minimal_publisher",
        "publisher_local_function",
        "my_talker_node",
        remaps={"/topic": "/test/better_launch/chatter_node"},
    )
    listener = bl.node(
        "examples_rclpy_minimal_subscriber",
        "subscriber_member_function",
        "my_listener_node",
        remaps={"/topic": "/test/better_launch/chatter_node"},
    )

    talker.start()
    listener.start()
    _assert_talker_listener_running(
        talker, listener, "/test/better_launch/chatter_node"
    )


def test_compose():
    """Verify running composable nodes works."""
    bl = BetterLaunch()

    with bl.compose("my_composer"):
        talker = bl.component(
            "composition",
            "composition::Talker",
            "my_talker_comp",
            remaps={"/chatter": "/test/better_launch/chatter_comp"},
        )

    # bl.compose returns a Composer that we could reuse, but even without it's possible to reuse an
    # already running composer node (even if it wasn't started with better_launch!)
    with bl.compose("my_composer", reuse_existing=True) as composer:
        listener = bl.component(
            package="composition",
            plugin="composition::Listener",
            name="my_listener_comp",
            remaps={"/chatter": "/test/better_launch/chatter_comp"},
        )

    _assert_talker_listener_running(
        talker, listener, "/test/better_launch/chatter_comp"
    )

    composer.shutdown("Test successful", timeout=10.0)
    assert not composer.is_running, "Composer failed to shutdown"


def test_include():
    """Verify including other launch files works (better_launch must be installed in the workspace)."""
    bl = BetterLaunch()

    bl.include("better_launch", "05_launch_arguments.launch.py", enable=True)

    talker = bl.query_node("/my_talker")
    assert talker is not None

    listener = bl.query_node("/my_listener")
    assert listener is not None

    # Included example doesn't use remaps
    _assert_talker_listener_running(talker, listener, "/topic")


def test_ros2_actions():
    """Verify running ROS2 actions works."""
    bl = BetterLaunch()

    ros2 = bl.ros2_actions(
        RosLaunchNode(
            package="examples_rclpy_minimal_publisher",
            executable="publisher_local_function",
            name="my_talker_ros2",
            remappings=[("topic", "/test/better_launch/chatter_ros2")],
        ),
        RosLaunchNode(
            package="examples_rclpy_minimal_subscriber",
            executable="subscriber_member_function",
            name="my_listener_ros2",
            remappings=[("topic", "/test/better_launch/chatter_ros2")],
        ),
    )

    bl.wait_for_topic("/test/better_launch/chatter_ros2", timeout=10.0)
    time.sleep(2.0)

    publishers = bl.shared_node.get_publishers_info_by_topic(
        "/test/better_launch/chatter_ros2"
    )
    assert "my_talker_ros2" in [p.node_name for p in publishers], (
        "Talker is not publishing on expected topic"
    )

    subscribers = bl.shared_node.get_subscriptions_info_by_topic(
        "/test/better_launch/chatter_ros2"
    )
    assert "my_listener_ros2" in [s.node_name for s in subscribers], (
        "Listener is not listening on expected topic"
    )

    ros2.shutdown("Test successful", timeout=10.0)
    assert not ros2.is_running, "ROS2LaunchWrapper failed to shutdown"


def test_process_method_signature():
    """Verify process() method has correct signature."""
    import inspect
    from better_launch import BetterLaunch

    sig = inspect.signature(BetterLaunch.process)
    params = list(sig.parameters.keys())

    # Must have cmd and name
    assert "cmd" in params, "Missing 'cmd' parameter"
    assert "name" in params, "Missing 'name' parameter"

    # Must NOT have ROS-specific params
    assert "remaps" not in params, "Should not expose 'remaps'"
    assert "params" not in params, "Should not expose 'params'"
    assert "raw" not in params, "Should not expose 'raw'"
    assert "package" not in params, "Should not expose 'package'"
    assert "log_level" not in params, "Should not expose 'log_level'"

    # Must have process-relevant params
    assert "env" in params, "Missing 'env' parameter"
    assert "output" in params, "Missing 'output' parameter"
    assert "on_exit" in params, "Missing 'on_exit' parameter"
    assert "max_respawns" in params, "Missing 'max_respawns' parameter"


def test_process_docstring():
    """Verify process() has proper docstring."""
    from better_launch import BetterLaunch

    doc = BetterLaunch.process.__doc__
    assert doc is not None, "Missing docstring"
    assert "Parameters" in doc, "Missing Parameters section"
    assert "Returns" in doc, "Missing Returns section"
    assert "cmd" in doc, "Missing cmd parameter docs"


if __name__ == "__main__":
    pytest.main(["-v"])
