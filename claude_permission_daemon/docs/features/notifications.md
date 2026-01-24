# Notifications Hook

You must read, understand, and follow all instructions in `./README.md` when planning and implementing this feature.

## Overview

I would like this application to also handle Claude's `Notification` hook, and send these notifications to me via Slack if I'm idle. These notifications (I believe) are not actionable, i.e. they're a one-way notification with no response needed. Be sure to update the application code, documentation (README), and tests, and ensure the tests pass.

In addition to this work, I'd also like the idle monitor to track how long the user has been idle or active, and for the application to include the current idle/active state and duration in log messages when it determines whether to send something via Slack or not.
