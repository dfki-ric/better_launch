# :snake: Python Launchfiles

???+ tip

    *better_launch* comes with many example launchfiles that will cover all the essentials and some advanced use cases. They can be found in the [repo](https://github.com/dfki-ric/better_launch/tree/main/examples/python). This chapter will serve as a more general introduction.

## Header
A *better_launch* python launchfile will usually start with the basic imports followed by your decorated main launch function: 

```python
from better_launch import BetterLaunch, launch_this

@launch_this
def my_launch_function():
    bl = BetterLaunch()
    ...
```

The [@launch_this](../../reference/better_launch/wrapper/#better_launch.wrapper.launch_this) decorator will start the launch process and run your function, or run it in an already running launch process in case the launchfile got included. It will also expose a `generate_launch_description` function in case the launchfile got included or run from ROS2. In this case, your launch function will be wrapped in an `OpaqueCoroutine`, so *better_launch*  will still be used for execution.

You may name the decorated function however you like, its name serves no purpose beyond self-documentation. Your function should start by creating an instance of [BetterLaunch](../../reference/better_launch/launcher/#better_launch.launcher.BetterLaunch). This instance will provide you access to all of the launch functions, like creating nodes, calling services, etc. It is also a singleton, so trying to instantiate it multiple times will always return the same instance.

## Launch Arguments
To add launch arguments, simply add them as function arguments. You should provide a type hint and/or default value so that passed arguments are resolved to the correct type on execution. If no default is provided the argument will be required.

```python
from better_launch import BetterLaunch, launch_this

@launch_this
def my_launch_function(i_like_haikus: bool):
    bl = BetterLaunch()
    print(i_like_haikus, type(i_like_haikus))
    ...
```

If you provide a docstring to your launch function it will be used to create a help text and argument descriptions for your launchfile. *better_launch* uses numpy style docstrings, as I think it is the most concise one, but all common docstring formats are supported.

```python
@launch_this
def my_launch_function(i_like_haikus: bool):
    """Launchfiles sprawl in knots / 
    One clean cut to banish chaos / 
    Silence, then motion.

    Parameters
    ----------
    i_like_haikus : bool
        I mean, who doesn't?
    """
    bl = BetterLaunch()
    print(i_like_haikus, type(i_like_haikus))
    ...
```

```bash
❯ bl ./haiku.launch.toml --help
Usage: bl ./haiku.toml [OPTIONS]

  Launchfiles sprawl in knots / One clean cut to banish chaos / Silence, then motion

Options:
  --i_like_haikus BOOLEAN      I mean, who doesn't?  [default: True]
```

## Doing Things
Most launch actions will be executed through the [BetterLaunch](../../reference/better_launch/launcher/#better_launch.launcher.BetterLaunch) instance you acquire in the beginning. One of the most common launch patterns is loading a config file, then passing it to a node. 

```python
from better_launch import BetterLaunch, launch_this

@launch_this
def my_launch_function():
    bl = BetterLaunch()
    
    params = bl.load_params("my_package", "my_config.yaml")
    with bl.group("my_namespace"):
        my_node = bl.node("my_package", "my_node.py", params=params)
        print(my_node.get_subscribed_topics())
```

Simple as that! Notice how we also acquired a reference to the node we started? This is possible because *better_launch* will execute all actions synchronously. Once the `bl.node` call returns the node's process is already underway. This allows you to do some advanced actions that are not possible in ROS2 launchfiles:

- Query a node's live parameters.
- Check if it is a lifecycle node and change its lifecycle state.
- Terminate or restart nodes. 
- List its topics, services, etc.
- Get a node's process ID.
- etc.

???+ note

    ROS2 (mildly) pushes the philosophy that the launch logic should be kept separate from runtime logic. It is up to you to decide what's appropriate for your launchfile/system.

## Common Helpers
Loading configs and running nodes are general enough to be considered building blocks. There are also some common patterns that build upon these Legos. These are collected in the [convenience](../../reference/better_launch/convenience/) and [gazebo](../../reference/better_launch/gazebo/) modules.

```python
from better_launch import BetterLaunch, launch_this, convenience

@launch_this
def my_launch_function():
    # Still need to create the instance first
    bl = BetterLaunch()
    
    convenience.joint_state_publisher()
    convenience.record_topics()
```

## Launching Launchfiles
Astute readers may have noticed that the above example launchfile was run using the `bl` command. While you can in fact run *better_launch* launchfiles using the good ol' `ros2 launch`, this will deprive you of some quality of life features:

1. `bl` offers auto-completion for launch arguments.
2. It provides auto-completion even for regular ROS2 launchfiles.
3. It resolves and starts all launchfiles much faster than `ros2 launch`.
4. *better_launch* becomes the main launch process instead of ROS2's `LaunchService`, ensuring clean termination.
