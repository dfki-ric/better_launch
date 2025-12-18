# :compass: Why better_launch?

*better_launch* is what I wish `ROS2 launch` would be: intuitive to use, simple to understand, easy to remember. It is **not** yet another abstraction layer over ROS2 launch; it is a **full replacement** with no required dependencies on the existing launch system.

Instead of dozens of imports and class instances for even the most basic tasks, your launch files could look as simple and beautiful as this:

```python
from better_launch import BetterLaunch, launch_this

@launch_this(ui=True)
def my_main(enable_x: bool = True):
    """
    This is how nice your launch files could be!
    """
    bl = BetterLaunch()

    if enable_x:
        bl.node(
            "examples_rclpy_minimal_publisher",
            "publisher_local_function",
            "example_publisher",
        )

    # Include other launch files, even regular ROS2 launch files!
    bl.include("better_launch", "ros2_turtlesim.launch.py")
```

```bash
$> bl my_package my_launch_file.py --enable_x True
```

*Do I have your attention? Read on to learn more!*
