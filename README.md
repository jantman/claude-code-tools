# claude-code-tools

My customizations for Claude Code.

* [claude_notify.sh](claude_notify.sh) - Claude notification script that sends "claude waiting" messages to Pushover, if my local machine has been idle for at least 10 seconds using [pushover.sh](https://github.com/jnwatts/pushover.sh/blob/94e35e196ce606922d25e60a666d11bfbb92bae2/pushover.sh)
* [settings.json](settings.json) - My Claude `~/.claude/settings.json` mainly for hooks

## Git Setup

I normally clone github.com repos over SSH, using my YuibKey for auth. This doesn't work great with Claude if I'm not physically at my computer, as I have no way of approving pushes (I do have GitHub API access set up for `gh` and GitHub.com MCP set up; it's just git pushes that have this issue). Here's the simple way of handling this for a repo that's already been cloned over SSH:

1. Change remote URL to HTTPS: `git remote set-url origin https://github.com/OWNER/REPO.git`
2. Configure local credential store: `git config --local credential.helper "store --file=.git/credentials"`
3. [Generate a new fine-grained PAT](https://github.com/settings/personal-access-tokens) with a name specific to the repo and host, expiration at the end of the year, repository access for just this one repo, and read/write access to Contents.
4. Create credentials file: `echo 'https://USERNAME:YOUR_PAT@github.com' > .git/credentials && chmod 600 .git/credentials`
