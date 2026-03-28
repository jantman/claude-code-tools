# Claude Code SSH Access to Remote Machines

## Problem Statement

Allow Claude Code to SSH to many LAN machines where:

- Primary SSH auth uses a local YubiKey (FIDO2/sk keys)
- Occasional fallback to username/password auth is needed
- Interactive `sudo` on remote machines requires password entry
- Many hosts -- per-host MCP server configuration is too much overhead without helper tooling
- All machines have bidirectional LAN connectivity (reverse tunnels are viable)

## Key Constraint: The Sandbox

The single biggest blocker is Claude Code's **network sandbox**. It proxies traffic through an HTTP/HTTPS-only proxy, meaning raw TCP connections (SSH on port 22) are blocked. The `excludedCommands` setting does **not** bypass network sandboxing ([anthropics/claude-code#29274](https://github.com/anthropics/claude-code/issues/29274)). `allowUnixSockets` is reportedly broken ([anthropics/claude-code#16076](https://github.com/anthropics/claude-code/issues/16076)). The only escapes are:

1. **MCP servers** (run outside the sandbox)
2. **`dangerouslyDisableSandbox: true`** (removes all protections)
3. **Running Claude Code directly on the remote machine**

---

## Top 10 Options (Ranked)

### 1. AiondaDotCom/mcp-ssh -- Native SSH MCP Server

**How it works:** An MCP server that shells out to your actual `ssh`/`scp` binaries. Auto-discovers hosts from `~/.ssh/config` and `~/.ssh/known_hosts`, including `Include` directives. Supports batch command execution across multiple hosts.

**Why #1:** Because it uses your native `ssh` binary, it inherits your entire SSH ecosystem -- ssh-agent with YubiKey keys, ControlMaster multiplexing, ProxyJump configs, and all `~/.ssh/config` settings. No duplicate host configuration. One MCP server handles all hosts.

| Criterion | Rating | Notes |
|-----------|--------|-------|
| YubiKey auth | Excellent | Uses native ssh-agent; YubiKey touch works normally |
| Password fallback | Supported | Via ssh config annotation or `sshpass` in SSH config |
| Interactive sudo | Partial | May need TTY allocation tricks; not a first-class feature |
| Multi-host scale | Excellent | Auto-discovers from ssh config; zero per-host overhead |
| Setup effort | Low-Medium | `npm install`, add to MCP config, done |

**Mitigations for weaknesses:**
- Pair with SSH ControlMaster (`ControlMaster auto`, `ControlPersist 10m`) to minimize YubiKey touches -- one touch per host, then reuse the socket for all subsequent commands.
- For sudo, you may need to pass passwords via `echo PASSWORD | ssh -t host 'sudo -S command'` patterns.

**Repo:** [github.com/AiondaDotCom/mcp-ssh](https://github.com/AiondaDotCom/mcp-ssh)

---

### 2. bvisible/mcp-ssh-manager -- Feature-Rich SSH MCP Server

**How it works:** A comprehensive MCP server with 37 tools across 6 groups: core SSH operations, sudo commands, file transfer, database operations, tunneling, and health monitoring. Supports ProxyJump with multi-hop bastion chains.

**Why #2:** The most feature-complete option. Has dedicated sudo tools, built-in file transfer, and connection profiles. The 37-tool footprint is large but can be selectively enabled (up to 92% context reduction). Slightly lower than #1 because it doesn't use native `ssh` and requires per-host connection profiles rather than reading `~/.ssh/config`.

| Criterion | Rating | Notes |
|-----------|--------|-------|
| YubiKey auth | Good | SSH agent support; depends on underlying library |
| Password fallback | Yes | Password stored in connection profiles |
| Interactive sudo | Yes | Dedicated sudo tools built-in |
| Multi-host scale | Good | Connection profiles, but requires defining each host |
| Setup effort | Medium | Node.js, configure connection profiles |

**Repo:** [github.com/bvisible/mcp-ssh-manager](https://github.com/bvisible/mcp-ssh-manager)

---

### 3. Bash `ssh` with `dangerouslyDisableSandbox` + ControlMaster

**How it works:** Disable the sandbox entirely, then Claude uses `ssh user@host "command"` directly via its Bash tool. Pre-establish ControlMaster connections so YubiKey touch only happens once per host.

**Why #3:** Zero additional tooling -- uses SSH directly. The tradeoff is disabling the entire sandbox, which removes protections against accidental network access, file system damage, etc.

| Criterion | Rating | Notes |
|-----------|--------|-------|
| YubiKey auth | Excellent | Native ssh-agent, ControlMaster reduces touches |
| Password fallback | Needs work | Requires `sshpass` or `expect` wrappers |
| Interactive sudo | Difficult | Needs `ssh -t` + password piping; fragile |
| Multi-host scale | Excellent | Uses `~/.ssh/config` directly |
| Setup effort | Low | One setting change; SSH config you already have |

**Setup:**
```json
// .claude/settings.json
{
  "permissions": {
    "dangerouslyDisableSandbox": true
  }
}
```

```ssh-config
# ~/.ssh/config
Host *
    ControlMaster auto
    ControlPath ~/.ssh/sockets/%r@%h-%p
    ControlPersist 10m
```

**Risk:** Any command Claude runs has full network and filesystem access with no sandbox. A hallucinated `rm -rf` or accidental data exfiltration has no guardrails.

---

### 4. MCP ShellKeeper (tranhuucanh) -- Stateful SSH Sessions

**How it works:** An MCP server that maintains stateful SSH terminal sessions. Unlike other options where each command is independent, this preserves working directory, environment variables, and shell state between commands. Supports file transfer up to 10MB.

**Why #4:** The stateful session model is a significant advantage for real sysadmin work (cd into a directory, set env vars, run a series of commands). Most other options lose state between commands. Lower rank because it's a newer project with less battle-testing.

| Criterion | Rating | Notes |
|-----------|--------|-------|
| YubiKey auth | Depends | On underlying SSH library implementation |
| Password fallback | Yes | Supported |
| Interactive sudo | Good | Stateful sessions make sudo + subsequent commands natural |
| Multi-host scale | Good | Multiple named sessions |
| Setup effort | Low-Medium | npm package |

**Reference:** [Hacker News discussion](https://news.ycombinator.com/item?id=45847880)

---

### 5. Ansible as SSH Intermediary

**How it works:** Claude generates and executes Ansible ad-hoc commands or playbooks. Ansible handles SSH connections (via its own ControlMaster), privilege escalation (`become: yes`), multi-host orchestration, and idempotent operations. There are dedicated Ansible skills/plugins for Claude Code.

**Why #5:** Excellent for fleet-scale operations and anything that should be idempotent (package installs, config changes, service management). Ansible's `become` feature handles sudo elegantly. Lower rank because it's overkill for simple "check this log file" tasks, and Ansible itself may be blocked by the sandbox (it uses SSH under the hood).

| Criterion | Rating | Notes |
|-----------|--------|-------|
| YubiKey auth | Good | Uses ssh-agent under the hood |
| Password fallback | Yes | `--ask-pass` or `ansible_ssh_pass` |
| Interactive sudo | Yes | `become: yes` + `ansible_become_pass` |
| Multi-host scale | Excellent | Inventory files, groups, patterns |
| Setup effort | Medium-High | Ansible installed, inventory configured, may need sandbox disabled |

**Ansible skills for Claude Code:** [github.com/sigridjineth/hello-ansible-skills](https://github.com/sigridjineth/hello-ansible-skills)

**Caveat:** If the sandbox blocks Ansible's SSH connections, you'll need `dangerouslyDisableSandbox` anyway, which erodes the advantage over option #3.

---

### 6. Claude Code Desktop Native SSH

**How it works:** The Claude Code Desktop app (Mac/Windows/Linux) has built-in SSH support. Click the environment dropdown, select "+ Add SSH connection," provide hostname/username/key path. Claude Code must be installed on the remote machine. Once connected, all operations (file edits, Bash commands) execute remotely.

**Why #6:** First-party, officially supported, no MCP servers needed. Lower rank because it requires Claude Code installed on every remote host, only works from the Desktop app (not CLI), and switching between many hosts is manual.

| Criterion | Rating | Notes |
|-----------|--------|-------|
| YubiKey auth | Partial | SSH config respected; needs physical touch per connection |
| Password fallback | Yes | Via SSH config |
| Interactive sudo | Yes | Claude's Bash tool runs on the remote; sudo works normally |
| Multi-host scale | Poor | Manual switching; one connection at a time |
| Setup effort | High | Install Claude Code on every remote host |

**Docs:** [Claude Code Desktop - SSH Sessions](https://code.claude.com/docs/en/desktop)

---

### 7. chouzz/remoteShell-mcp -- Persistent Connections with Paramiko

**How it works:** Python MCP server using Paramiko for persistent SSH connections. Supports password and key auth. SFTP file transfer built-in. Connection profiles saved in `~/.remoteShell/config.json`.

**Why #7:** Persistent connections are valuable, and the Python ecosystem may be more comfortable than Node.js for some users. Lower rank because Paramiko (Python SSH library) does **not** natively support FIDO2/sk keys (YubiKey), which is a significant limitation for this use case.

| Criterion | Rating | Notes |
|-----------|--------|-------|
| YubiKey auth | Poor | Paramiko lacks FIDO2/sk key support |
| Password fallback | Yes | Primary auth method |
| Interactive sudo | Partial | Not explicitly documented |
| Multi-host scale | Good | Multiple named connection profiles |
| Setup effort | Low-Medium | pip install, configure profiles |

**Workaround for YubiKey:** Pre-establish ControlMaster connections with native ssh, then configure Paramiko to use the ControlMaster socket. This is fragile and unsupported.

**Repo:** [github.com/chouzz/remoteShell-mcp](https://github.com/chouzz/remoteShell-mcp)

---

### 8. SSHFS + Bash SSH Hybrid

**How it works:** Mount remote filesystems locally via SSHFS so Claude can read/edit files with its native tools. Run remote commands via `ssh` (requires sandbox workaround). The [sochowski/claude-remote](https://github.com/sochowski/claude-remote) project provides a wrapper for this pattern.

**Why #8:** Good for file-heavy workflows (code review, config editing) where most work is reading/writing files. File operations bypass the sandbox entirely since they look local to Claude. Lower rank because command execution still requires SSH (sandbox issue) and SSHFS can be flaky.

| Criterion | Rating | Notes |
|-----------|--------|-------|
| YubiKey auth | Good | For the mount; ControlMaster keeps it alive |
| Password fallback | Yes | Standard SSH auth for mount |
| Interactive sudo | No | Files only; command execution needs separate SSH |
| Multi-host scale | Medium | One mount point per host; manageable with scripts |
| Setup effort | Medium | Install SSHFS, create mount points, manage lifecycle |

**Setup sketch:**
```bash
# Mount remote filesystem
sshfs user@host:/path /mnt/remote-host -o ControlMaster=auto,ControlPersist=10m

# Claude can now read/edit /mnt/remote-host/* natively
# Remote commands still need: ssh user@host "command"
```

---

### 9. Custom MCP Server Wrapping Native SSH

**How it works:** Write a lightweight MCP server (Python or TypeScript) that wraps `subprocess.run(["ssh", ...])` calls. Since MCP servers run outside the sandbox, SSH works. Reads hosts from `~/.ssh/config`. Can include sudo support via `ssh -t host 'sudo -S command'` with password piped from a secure store.

**Why #9:** Maximum control and customization for your exact requirements. Lower rank because it's a build-it-yourself approach, but it may end up being the best long-term solution if no existing MCP server handles YubiKey + sudo + multi-host well enough.

| Criterion | Rating | Notes |
|-----------|--------|-------|
| YubiKey auth | Excellent | Native ssh binary + ssh-agent |
| Password fallback | Yes | Implement however you want |
| Interactive sudo | Yes | Full control over TTY/password handling |
| Multi-host scale | Excellent | Read from ssh config; no per-host MCP config |
| Setup effort | High | Must write and maintain the server |

**Starting point:** The [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) or [MCP TypeScript SDK](https://github.com/modelcontextprotocol/typescript-sdk) make this straightforward. A minimal implementation is ~100 lines.

---

### 10. Install Claude Code on Remote Machines + `--remote-control`

**How it works:** SSH into each remote machine, install Claude Code, run `claude --remote-control` inside tmux. Access from claude.ai/code, iOS/Android app, or any browser. Each remote machine has its own Claude session with full local access.

**Why #10:** The "just put Claude there" approach. No SSH-from-Claude complexity at all -- Claude runs locally on the target. Lower rank because it requires installation on every host, each host is a separate session (no unified view), API keys/tokens must be distributed, and it doesn't help with cross-machine workflows.

| Criterion | Rating | Notes |
|-----------|--------|-------|
| YubiKey auth | N/A | Claude runs locally; no SSH needed |
| Password fallback | N/A | No SSH |
| Interactive sudo | Yes | Native sudo works; Claude's Bash tool handles it |
| Multi-host scale | Poor | Separate install, session, and credentials per host |
| Setup effort | High | Install everywhere; manage API keys/tokens |

**Docs:** [Claude Code Remote Control](https://code.claude.com/docs/en/remote-control), [Headless Mode](https://code.claude.com/docs/en/headless)

---

## Quick Comparison Matrix

| Rank | Option | YubiKey | Password | Sudo | Multi-Host | Sandbox | Effort |
|:----:|--------|:-------:|:--------:|:----:|:----------:|:-------:|:------:|
| 1 | AiondaDotCom/mcp-ssh | ++ | + | ~ | ++ | Bypassed | Low |
| 2 | bvisible/mcp-ssh-manager | + | ++ | ++ | + | Bypassed | Med |
| 3 | Bash + disable sandbox | ++ | ~ | - | ++ | Disabled | Low |
| 4 | MCP ShellKeeper | ? | + | + | + | Bypassed | Low |
| 5 | Ansible intermediary | + | + | ++ | ++ | Needs fix | Med-Hi |
| 6 | Desktop native SSH | ~ | + | ++ | - | N/A | High |
| 7 | chouzz/remoteShell-mcp | -- | ++ | ~ | + | Bypassed | Low |
| 8 | SSHFS + SSH hybrid | + | + | -- | ~ | Partial | Med |
| 9 | Custom MCP server | ++ | ++ | ++ | ++ | Bypassed | High |
| 10 | Install on remotes | N/A | N/A | ++ | -- | N/A | High |

Legend: `++` excellent, `+` good, `~` partial, `-` poor, `--` very poor, `?` unknown

## Decision

**Selected: Option #2 -- bvisible/mcp-ssh-manager.** The dedicated sudo tools, built-in file transfer, and comprehensive feature set outweigh the per-host connection profile overhead. The 37-tool footprint can be managed via selective tool group enabling (up to 92% context reduction). Connection profiles can be scripted/templated for many hosts.

### Runners-up considered

- **AiondaDotCom/mcp-ssh (#1)** was the top-ranked option for its native `ssh` integration and auto-discovery from `~/.ssh/config`, but its sudo support is only partial and would require workarounds.
- **Custom MCP server (#9)** remains a viable fallback if bvisible/mcp-ssh-manager proves insufficient -- full control over TTY allocation and password handling in ~100 lines.

## Relevant GitHub Issues

- [anthropics/claude-code#29274](https://github.com/anthropics/claude-code/issues/29274) -- `excludedCommands` doesn't bypass network sandbox
- [anthropics/claude-code#16076](https://github.com/anthropics/claude-code/issues/16076) -- `allowUnixSockets` not working
- [anthropics/claude-code#24091](https://github.com/anthropics/claude-code/issues/24091) -- Feature request: per-host SSH/TCP allowlist
- [anthropics/claude-code#34402](https://github.com/anthropics/claude-code/issues/34402) -- Regression: local network SSH blocked

---

*Generated 2026-03-28 by Claude Code*
