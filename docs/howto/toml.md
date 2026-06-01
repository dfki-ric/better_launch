# :t_rex: TOML Launchfiles

The discussions over at ros discourse revealed that there was a need for launchfiles that are not code-based but can be parsed offline. TOML launchfiles provide exactly that: the full power of *better_launch* while limiting the complexity that would be achievable through python.

???+ tip

    This page will give you a general overview. Have a look at the [examples](https://github.com/dfki-ric/better_launch/tree/main/examples/toml) for more details!

???+ example "Feedback welcome!"

    The TOML format is an entirely new way of writing launchfiles. While I have faith in the general approach, it may not quite meet the needs yet. [Feedback](https://github.com/dfki-ric/better_launch/issues) is very much welcome!

## Call Tables
In TOML launchfiles most tables are so-called *call tables*. These are dictionaries with a `func` key referring to one of the public [BetterLaunch](../../reference/better_launch/launcher/#better_launch.launcher.BetterLaunch) member functions (the [convenience](../../reference/better_launch/launcher/#better_launch.convenience) and [gazebo](../../reference/better_launch/launcher/#better_launch.gazebo) modules are also supported). Most other attributes are treated as keyword arguments to that function. Just like with python launchfiles, call tables are executed in order of appearance, and their return values are stored under the table’s name.

For example, the following call table will call [bl.find](../../reference/better_launch/launcher/#better_launch.launcher.BetterLaunch.find), pass `better_launch` as the package and `cube.sdf` as the filename, then store the returned value under `a_simple_cube`.

```toml
[a_simple_cube]
func = "find"
package = "better_launch"
filename = "cube.sdf"
```

???+ warning

    Every call table *must* have a unique name even if the call doesn't have a result or the result is not used!

## Substitutions
Substitutions take heavy inspiration from those found in ROS1 and should be familiar to many. However, as the TOML launchfile format is much more powerful, only the following substitutions were 
deemed necessary for now:

  - `${<K>}`: value of launch argument or call table `<K>`
  - `${param <N> <P>}`: query node `<N>` for its ROS2 parameter `<P>`
  - `${env <E> <D>}`: environment variable `<E>` (default `<D>`)
  - `${eval <X>}`: evaluate Python expression `<X>` (disabled by default)

Substitutions may be nested (inner ones resolve first). The following call table will log the path of the cube we previously located:

```toml
[print_cube]
func = "log"
severity = "info"
message = "A simple cube can be found at ${a_simple_cube}"
```

???+ important

    `eval` poses a security risk and is therefore disabled by default. This can be changed by creating a global launch argument `bl_eval_mode` and setting it to either `full` (regular `eval`) or `literal_eval` (only parses literal values).

## Conditions
Call tables can be made conditional by adding an `if` or `unless` parameter. The table will only run if this value evaluates to true (or false for `unless`) according to python truthiness. Be aware that non-empty strings are also considered true. If a call table doesn't run or has no return, `None` will be stored under its name.

## Launch Arguments
Launch arguments can be defined as global parameters before the first table. Their values can be used in substitutions just like any call table result. In addition, you may set the `bl_allow_kwargs` so arbitrary launch arguments can be passed to the launchfile (i.e. for nodes that consume the additional inputs).

In order to support required launch arguments, *better_launch* makes a small extension to TOML: when defining your launch arguments, instead of assigning them a value you may also assign them one of python's primitive types *without quotes* (e.g. `my_arg = bool`). The launchfile will then require this argument to be passed and handle it as the specified type.

## Namespaces & Components
When using functions like [bl.group](../../reference/better_launch/launcher/#better_launch.launcher.BetterLaunch.group) and [bl.compose](../../reference/better_launch/launcher/#better_launch.launcher.BetterLaunch.compose) that create a python context, you have to add the elements belonging to them as *children* using the following syntax:

```toml
[my_composer]
func = "compose"

[my_composer.children.talker]
func = "component"
package = "composition"
plugin = "composition::Talker"
```

You may also use TOML table arrays. In this case the children will get assigned a key according to their index (order of appearance). These two patterns cannot be mixed.

```toml
# key will be my_composer.children.0
[[my_composer.children]]
...

# key will be my_composer.children.1
[[my_composer.children]]
...
```

## Convenience & Gazebo
By default, call tables will lookup the function to run on the [BetterLaunch](../../reference/better_launch/launcher/#better_launch.launcher.BetterLaunch) instance. To run functions from the [convenience](../../reference/better_launch/convenience/) or [gazebo](../../reference/better_launch/gazebo/) modules, you may specify a `context` parameter and pass it either `convenience` or `gazebo`. This *cannot*  be used to run code from arbitrary modules - only these values are supported.

For example, the following call table will start a rosbag recording:

```toml
[start_recording]
context = "convenience"
func = "record_topics"
```

# Comments & Docstrings
While TOML has support for comments (using `#`), existing parsers either don't preserve them, make no association between comments and values, or simply don't work for all cases. The TOML parser in *better_launch* treats any block of comments immediately preceding a key-value pair as belonging to it. This is relevant for any launch arguments you define, as their associated comments will be turned into help text for the command line. In addition, a comment block at the top of the file followed by a blank line will be treated as the launchfile's docstring.

```toml
# Launchfiles sprawl in knots / 
# One clean cut to banish chaos / 
# Silence, then motion

# I mean, who doesn't?
i_like_haikus = True
```

```bash
❯ bl ./haiku.launch.toml --help
Usage: bl ./haiku.toml [OPTIONS]

  Launchfiles sprawl in knots / One clean cut to banish chaos / Silence, then motion

Options:
  --i_like_haikus BOOLEAN      I mean, who doesn't?  [default: True]
```
