#!/usr/bin/env bash
# managed by privatepuppet::claude

# /home/jantman/bin/pushover.sh -t "Claude Waiting" $1
# sends the pushover notification that claude is waiting for input, and its current directory
#
# swayidle timeout 10
# runs the specified command after 10 seconds of idle time (waits indefinitely until idle time reached)
#
# timeout --foreground 12
# runs the specified command, but kills it after 12 seconds (so swayidle doesn't run indefinitely)
#
# Uses: https://github.com/jnwatts/pushover.sh/blob/94e35e196ce606922d25e60a666d11bfbb92bae2/pushover.sh
timeout --foreground 12 swayidle timeout 10 "/home/jantman/bin/pushover.sh -t \"$(hostname) Claude Waiting\" \"$(hostname) - $1\""
