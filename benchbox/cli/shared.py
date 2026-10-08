from benchbox.utils.printing import (
    quiet_console,
    set_quiet as set_quiet_output,
    silence_output,
)

console = quiet_console

__all__ = ["console", "set_quiet_output", "silence_output"]
