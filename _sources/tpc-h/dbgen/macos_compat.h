/* macOS compatibility header - auto-generated */
#ifndef MACOS_COMPAT_H
#define MACOS_COMPAT_H

#ifdef MACOS_COMPAT
/* Use system getopt on macOS to avoid conflicts */
#include <unistd.h>
#ifdef getopt
#undef getopt
#endif
#endif

#endif /* MACOS_COMPAT_H */
