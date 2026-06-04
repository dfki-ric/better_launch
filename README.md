![Logo](docs/assets/images/logo_text.png)

> [!TIP]
> Just looking for the [documentation](https://dfki-ric.github.io/better_launch/)? 
> We also have various [examples](examples/)!

---

# 🧭 About
Let's face it: ROS2 has been a severe downgrade in terms of usability compared to ROS1. While there are many considerable improvements, the current launch system is borderline unusable. 

*better_launch* is what I wish ROS2 launch would be: intuitive to use, simple to understand, easy to remember. This is why *better_launch* is **not** yet another abstraction layer over ROS2 launch; it is a **full replacement** with no required dependencies on the existing launch system.

Instead of dozens of imports and class instances for even the most basic tasks, your launchfiles could look as simple and beautiful as this:

```python
from better_launch import BetterLaunch, launch_this

@launch_this
def my_main(enable_x: bool = True):
    """This is how nice your launchfiles could be!
    """
    bl = BetterLaunch()

    if enable_x:
        bl.node(
            "examples_rclpy_minimal_publisher",
            "publisher_local_function",
            "example_publisher",
        )

    # Include other launchfiles, even regular ROS2 launchfiles!
    bl.include("better_launch", "ros2_turtlesim.launch.py")
```

```bash
# You can use `ros2 launch`, too, but `bl` is better :)
$> bl my_package my_launch_file.py --enable_x True
```

*Do I have your attention? Read on to learn more!*
- [The What and Why](https://dfki-ric.github.io/better_launch/about/why/)
- [Differences to ROS2](https://dfki-ric.github.io/better_launch/about/differences/)
- [Installation](https://dfki-ric.github.io/better_launch/installation/installation/)
- [HowTo](https://dfki-ric.github.io/better_launch/howto/python/)
- [Examples](examples/python)

# 🧞‍♀️ Highlights

## 🪄 Complete replacement

> [!NOTE]
> [All features](https://dfki-ric.github.io/better_launch/about/features/)

*better_launch* can do everything that ROS2 launchfiles can, but more, with equal or less resources, and better:
- Solve almost every task with 2-3 imports
- Actions are executed in sequence, nodes shutdown in reverse
- Shell autocompletion for launch arguments
- Use natural types instead of strings of lists of dicts of...
- Include regular ROS2 launch files and get included by them

## 📟 The TUI

> [!NOTE]
> [Using the TUI](https://dfki-ric.github.io/better_launch/howto/tui/)

*better_launch* comes with an optional, unobstrusive TUI (terminal user interface) based on [prompt_toolkit](https://github.com/prompt-toolkit/python-prompt-toolkit), which will hover below the log output. 

![TUI](docs/assets/images/tui.png)

See the single line of shortcuts at the bottom? That's the TUI, and it will never take up more than 3 lines! Despite its simplicity, the TUI allows you a comfortable degree of control over all nodes managed by the *better_launch* process it is running in:
- listing a node's services and topics
- starting and stopping nodes
- triggering lifecycle transitions
- changing the log level
- etc.

```bash
# Run this line to see it in action!
bl better_launch 02_ui.launch.py
```

## ⛱️ TOML launchfiles

> [!NOTE]
> [Specification](https://dfki-ric.github.io/better_launch/howto/toml/)

For those with aversions against using a turing-complete programming language to specify system startup - fear not! *better_launch* introduces a new launchfile format based on [TOML](https://toml.io/). 

```toml
enable = true

[a_simple_cube]
if = "${enable}"
func = "find"
package = "better_launch"
filename = "cube.sdf"

[print_me_baby]
func = "log"
severity = "info"
message = "Found cube at ${a_simple_cube}"
```

Under the hood, TOML launchfiles result in calls to the `BetterLaunch` singleton, but offer a more focused and constrained feature set (limited branching, no loops, etc.). If you are still missing ROS1 XML launchfiles (and substitutions like `${arg my_arg}`), these are for you!


# 🌱 Contributions

> [!IMPORTANT]
> Please [see this document](CONTRIBUTING.md) if you're planning to make PR!

*Author:* [Nikolas Dahn](https://github.com/ndahn/)

*Testing & Feedback:*
- [Tom Creutz](https://github.com/tomcreutz)
- [Prithvi Sanghamreddy](https://github.com/Prithvi-Sanghamreddy)
- [Sebastian Kasperski](https://github.com/skasperski)

*better_launch* was initiated and is currently developed at the [Robotics Innovation Center](http://robotik.dfki-bremen.de/en/startpage.html) of the [German Research Center for Artificial Intelligence (DFKI)](http://www.dfki.de) in Bremen.

---

*Copyright 2026, [DFKI GmbH](http://www.dfki.de) / [Robotics Innovation Center](http://robotik.dfki-bremen.de/en/startpage.html)*

![dfki-logo](docs/assets/images/dfki.png)