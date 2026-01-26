# Mac and Windows Support

You must read, understand, and follow all instructions in `./README.md` when planning and implementing this feature.

## Overview

Currently this application is written for Linux with Wayland and uses `swayidle` to detect when the system is idle. We need to add support for idle detection on Mac and Windows, and automatically choose the proper idle detection backend for the current operating system. If no appropriate idle backend can be found, the daemon should exit non-zero with an error message explaining what the problem is and how to resolve it.
