# :gear: Settings

*better_launch* has a few settings that can be set from launchfiles or externally. 

Every option listed here can be set in the launchfile, as an environment variable, or passed as a command line argument. The priority order is always `CLI > env > launchfile`. Their names slightly change depending on where you define them:

- In python launchfiles, pass them in lowercase to the [@launch_this](../../reference/better_launch/wrapper/#better_launch.wrapper.launch_this) decorator (e.g. `ui=True`).
- For [TOML lanuchfiles](../howto/toml.md), define them as global launch arguments and add a `bl_` prefix (so `ui` becomes `bl_ui`).
- As environment variables they become uppercase and get a `BL_` prefix (so `ui` becomes `BL_UI`).
- On the command line they get a `--bl-` prefix and underscores become dashes (so `ui` becomes `--bl-ui`). 

???+ example "ui *(bool)*"
    
    Enables or disables the [terminal UI](../howto/tui.md).

???+ example "colormode *(string)*"
    
    How to apply colors to terminal logging output.

    - default: uniform highlight for node names, colored severity levels.
    - severity: colored severity levels.
    - source: colored node names.
    - none: no colors.
    - rainbow: colored node names, colored severity levels.

???+ example "print_limit *(int)*"
    
    Limits the character length of messages printed to the terminal. No limit if <= 0.

???+ example "screen_log_level *(int)*"
    
    Only print messages to the terminal if they have at least this severity (based on python's logging module). , as defined in python's logging module (10 = DEBUG, 20 = INFO, etc).

???+ example "file_log_level *(int)*"
    
    Only write messages to log files if they have at least this severity (see above).

???+ example "screen_log_format *(string)*"
    
    Overrides the format for messages logged to the terminal. Check the [PrettyLogFormatter](../../reference/better_launch/utils/better_logging/) for valid syntax.

???+ example "file_log_format *(string)*"
    
    Overrides the format for messages logged to log files, following the same format as the screen log format.
