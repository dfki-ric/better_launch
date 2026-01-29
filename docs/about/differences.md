# :balance_scale: What are the differences?
Because *better_launch* does not use the ROS2 launch system, some aspects work differently from what you may be used to.


## Action immediacy
In ROS2 launch, launchfiles create tasks that are then passed to an asynchronous event loop. This is the reason why e.g. checking for launch parameter values is so incredibly weird - they simply don't exist yet by the time you define the actions. In *better_launch* however, all actions are taken immediately: if you create a node, its process is started right away; if you include another launchfile, its contents will be handled before the function returns. 

The only exception to this is adding ROS2 launch actions, e.g. by including regular ROS2 launchfiles. Since these still rely on the ROS2 launch system, they need to be turned into asynchronous tasks and passed to the event loop. Usually a ROS2 `LaunchService` sub-process is started the first time a ROS2 action is passed to *better_launch*. From then on this process will handle all ROS2 actions asynchronously in the background. 

???+ info

    While the output of the ROS2 launch service process (and its nodes) is captured and formatted by *better_launch* just like for all other nodes, these will usually appear and behave as one single `launch_service` unit in the TUI.


## Lifecycle nodes
Lifecycle nodes differ from regular nodes in that they don't become fully active after their process starts. Instead you have to call one of their lifecycle management services, usually via additional code in your launchfile or the `ros2 lifecycle` CLI. However, in the end they are still just nodes.

*better_launch* makes no distinction between regular and lifecycle nodes. Instead, all "lifecyclable" objects (e.g. nodes and components) provide a `LifecycleManager` object via their `lifecycle` member. This will be `None` if the object has not been identified (yet) as a lifecycle-thing - otherwise you can use it to manage the object's lifecycle. 

???+ note

    All objects that turn out to be lifecyclable will transition to their *ACTIVE* state by default, unless you pass a different target state on instantiation.


## Type checking
When passing arguments to a node in ROS2, it is ultimately passed as a stringified command line argument. So why bother with overly strict type checking? Why do I have to turn half the parameters into strings myself? *better_launch* does not impose a flawed type sytem on you and will happily accept `int`, `string`, `float`, etc. where appropriate. In addition, sensible and *unsurprising* types have been chosen for all arguments you may provide (e.g. remaps are defined as a `dict[str, str]`, floats are happy to accept ints, launch arguments are never required to be strings, etc.).


## Declaring launch arguments
Simply put: you don't. *better_launch* will check the signature of your launch function and turn all arguments into launch arguments. For example, if your launch function has an `enable_x` argument, you will be able to pass it with `--enable_x <value>` from the command line. Under the hood *better_launch* is using [click](https://click.palletsprojects.com/), so every launchfile you write comes with proper CLI support. 

???+ tip

    Tip: try adding a docstring to your launch function and call your launchfile with `--help`!


## Parameter files
You do **not** have to put `ros__parameters` in your configs anymore when using `BetterLaunch.load_params`. Hooray! You still can do so of course if you feel slightly masochistic. In fact, *better_launch* supports the full param syntax for mapping params to nodes, including namespace wildcards. See the [load_params](../../reference/better_launch/launcher/#better_launch.launcher.BetterLaunch.load_params) documentation for details.


## Logging
Just like ROS2 launch, *better_launch* takes care of managing loggers and redirecting everything where it belongs (in fact that part is largely copied from ROS2 launch). However, I did away with the in my opinion not very useful separation between a node's `stdout` and `stderr`, since nodes apparently write their log output to `stderr` by default. 

I also added a reformatting layer so that colors and nicer screen output are possible. The format can be customized by passing your own logging format strings to the [launch_this](../../reference/better_launch/wrapper/#better_launch.wrapper.launch_this) decorator. However, it is recommended to set the `BL_SCREEN_LOG_FORMAT` and `BL_FILE_LOG_FORMAT` environment variables instead.


## Abandoned processes
ROS2 launch has a bad reputation of leaving stale and abandoned processes behind after terminating. In my testing so far this has never been an issue with *better_launch* yet - except when you hard kill (-9) the *better_launch* process.
