# :thinking_face: Why not improve ROS2 launch?
Because I think it is beyond redemption and no amount of refactoring and REPs (ROS enhancement proposals) will turn the sails. While tools like [simple_launch](https://github.com/oKermorgant/simple_launch) or [launch-generator](https://github.com/Tacha-S/launch_generator/) exist, they still use ROS2 launch under the hood and so inherit much of its clunkiness. Rather than fixing an inherently broken solution, I decided to make a RAP - a ROS abandonment proposal :)

Here is a "simple" launch file from the [official documentation](https://docs.ros.org/en/jazzy/Tutorials/Intermediate/Launch/Using-Substitutions.html) that does nothing but include another launch file:

```python
from launch_ros.substitutions import FindPackageShare

from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import PathJoinSubstitution, TextSubstitution


def generate_launch_description():
    colors = {
        'background_r': '200'
    }

    return LaunchDescription([
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource([
                PathJoinSubstitution([
                    FindPackageShare('launch_tutorial'),
                    'launch',
                    'example_substitutions_launch.py'
                ])
            ]),
            launch_arguments={
                'turtlesim_ns': 'turtlesim2',
                'use_provided_red': 'True',
                'new_background_r': TextSubstitution(text=str(colors['background_r']))
            }.items()
        )
    ])
```

I think we can agree that this is not exactly elegant - including another launch file should be doable within a single line, not 10 plus 5 imports. Other terrible decisions within ROS2 launch include, but are not limited to:

- a weird fetish for unintuitive import statements (see above)
- unneccesarily strict type checking (why use python if I have to verify everything?)
- nonsensical argument types (e.g. remaps are a *list of tuples* instead of simply a *dict*)
- using asyncio may be slightly faster, but prevents normal variable interactions (ever wondered why you always see these weird `Condition` classes instead of a simple `if my_arg:`?)
- horrendous API for starting lifecycle nodes (also, why the hell are there two completely separate base interfaces?)
- the list goes on...

For comparison, here is what the above launch file will look like in *better_launch*:

```python
from better_launch import BetterLaunch, launch_this

@launch_this
def main(turtlesim_ns = "turtlesim2", use_provided_red = True, new_background_r = 200):
    bl = BetterLaunch()

    bl.include(
        "launch_tutorial", 
        "example_substitutions.launch.py",
        pass_all_args=True,  # or pass as keyword arguments
    )
```

Overall, ROS2 launch seems like a system architect's wet fever dream, and I don't enjoy it.
