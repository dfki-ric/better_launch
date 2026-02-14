#!/usr/bin/env python3
"""Simple timed talker that outputs at a configurable rate."""

import rclpy
from rclpy.node import Node
from std_msgs.msg import String


class TimedTalker(Node):
    def __init__(self):
        super().__init__("my_timer")
        self.declare_parameter("period", 1.0)
        self._period = self.get_parameter("period").value
        self.get_logger().info(f"Publishing with period={self._period}s")
        self._pub = self.create_publisher(String, "chatter", 10)
        self._timer = self.create_timer(self._period, self._callback)
        self._count = 0

    def _callback(self):
        msg = String()
        msg.data = f"Hello World: {self._count}"
        self.get_logger().info(f'Publishing: "{msg.data}"')
        self._pub.publish(msg)
        self._count += 1


def main(args=None):
    rclpy.init(args=args)
    try:
        rclpy.spin(TimedTalker())
    except KeyboardInterrupt:
        pass
    finally:
        rclpy.shutdown()


if __name__ == "__main__":
    main()
