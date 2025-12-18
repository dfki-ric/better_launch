# :tools: How do I use it?
The best way to get to know *better_launch* is to explore the included [examples](../examples.md). Unlike ROS2, all examples and functions come with proper [documentation](../../reference/better_launch/). If anything is left unclear, feel free to contact me.

You will mainly interact with *better_launch* through the following classes and modules:

- [@launch_this](../../reference/better_launch/wrapper/#better_launch.wrapper.launch_this): decorator to create a launch file from a function.
- [BetterLaunch](../../reference/better_launch/launcher/#better_launch.launcher.BetterLaunch): to create and start nodes, include other launch files, find and load parameters, etc.
- [convenience.py](../../reference/better_launch/convenience/): convenience functions to start rviz, robot state publishers, read urdf/xacro files, record rosbags, and more.
- [gazebo.py](../../reference/better_launch/gazebo/): functions and helpers for starting and populating gazebo simulations as well as bridging topics.

Note that you are not forced to choose between *better_launch* and the ROS2 launch system. In fact, *better_launch* launch files can be run via `ros2 launch` and even be included from ROS2 launch files! However, this means running two launch systems on top of each other, so there is some overhead. The auto completion of `ros2 launch` is also slow as hell, cluttering the terminal with useless command line options yet is unable to discover the arguments you have declared inside your launch files. For these reasons, *better_launch* comes with the `bl` script, which fixes all of the above and then some. Once you have sourced your workspace you can use it as follows:

```bash
# Try <tab><tab> for autocomplete and check the example launch file for details!
bl better_launch 05_launch_arguments.py --help
```
