# :gear: Configuration

*better_launch* has a few settings that can be set from launchfiles or externally. The priority order is always `launchfile < env < CLI`. 

> TODO

- `BL_UI` (*enable|disable*): enables or disables the UI for all launch files. Superseded by the `--bl_ui` argument.
- `BL_COLORMODE` (*default|severity|source|none|rainbow*): overrides the colormode for all launch files. Superseded by the `--bl_colormode` argument.
- `BL_SCREEN_LOG_FORMAT`: overrides the format for messages logged to the terminal. Check the [PrettyLogFormatter](../../reference/better_launch/utils/better_logging/) for valid syntax.
- `BL_FILE_LOG_FORMAT`: overrides the format for messages logged to log files, following the same format as the screen log format.
