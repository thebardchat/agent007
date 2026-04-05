# CLAUDE.md — Angel Cloud CLI Cluster Project
> Claude Code context file. Read this first before touching anything.

---

## WHO I AM
Shane Brazelton. Dispatch manager, coach, developer, father of five. ADHD — keep responses short, direct, actionable. No fluff.

---

## THE MISSION
Build Angel Cloud CLI to manage a distributed home cluster across multiple machines, with headless nodes that stay online and useful even when laptops are closed. This feeds into the bigger vision: ShaneBrain → Angel Cloud → Pulsar AI → TheirNameBrain → 800M users losing Windows 10 support.

---

## CLUSTER ARCHITECTURE

| Node | Hostname | Tailscale IP | Role |
|------|----------|--------------|------|
| Pi 5 (16GB) | shanebrain-1 | 100.67.120.6 | Core coordinator, local AI |
| Pulsar0100 | pulsar0100 | 100.81.70.117 | N8N automation bridge |
| Laptops (2-5) | TBD | TBD | Headless cluster nodes |

**Pi 5 Core Stack:**
- Ollama (llama3.2:1b) — local inference
- Weaviate (ports 8080/50051) — vector DB / RAG
- Open WebUI (port 3000) — UI
- FastMCP server (port 8008) — ShaneBrain MCP
- Claude Code v2.1.37
- All core files: `/mnt/shanebrain-raid/shanebrain-core/`
- RAID 1 NVMe — do NOT write outside this path unless necessary

**Pulsar0100:**
- N8N automation (runs every 30 min)
- Claude Code
- SSH key auth established to Pi

**Network:** All machines connected via Tailscale. Use Tailscale IPs, NOT MagicDNS hostnames (unreliable).

---

## HEADLESS NODE REQUIREMENTS

Every cluster node (laptop or desktop) must:

- [ ] Have Tailscale installed and connected
- [ ] Run a lightweight cluster agent daemon (systemd service on Linux, Task Scheduler on Windows)
- [ ] Stay connected even when lid is closed / screen is off
- [ ] Disable aggressive sleep/hibernate (Wi-Fi must stay active)
- [ ] Accept SSH from Pi coordinator using key-based auth
- [ ] Report health status back to Pi on a schedule
- [ ] Never require manual login to stay in cluster

**Windows Sleep Fix (per laptop):**
```powershell
powercfg /change standby-timeout-ac 0
powercfg /change standby-timeout-dc 0
powercfg /setacvalueindex SCHEME_CURRENT 19cbb8fa-5279-450e-9fac-8a3d5fedd0c1 12bbebe6-58d6-4636-95bb-3217ef867c1a 0
```

**Linux/Mac:**
- Edit `/etc/systemd/sleep.conf` — set `SuspendState=off`
- Or use `caffeine` / `pmset -a sleep 0` on Mac

---

## ANGEL CLOUD CLI — COMMANDS TO BUILD

```
angel-cloud deploy [service] [--env local|vps|cluster]
angel-cloud status [--node all|pi|pulsar|laptop-1...]
angel-cloud health
angel-cloud logs [service] [--tail 50]
angel-cloud rollback [service]
angel-cloud mcp list
angel-cloud mcp status [server-name]
angel-cloud cluster add [tailscale-ip]
angel-cloud cluster remove [tailscale-ip]
angel-cloud cluster sync
angel-cloud notify test
```

---

## MCP INTEGRATION

- ShaneBrain MCP lives on Pi at port 8008 (FastMCP, Python)
- CLI must discover available MCP servers across all nodes
- Route requests to the appropriate node's MCP server
- Display tool availability per node with `angel-cloud mcp list`
- MCP health included in `angel-cloud health` output

---

## DISCORD NOTIFICATIONS

All critical events push to Discord webhook:
- Deployment start / success / failure
- Node goes offline / comes back online
- Rollback triggered
- MCP server down

Environment variable: `ANGEL_CLOUD_DISCORD_WEBHOOK`

Format:
```json
{
  "content": "🚀 [angel-cloud] Deploy SUCCESS — angel-cloud-roblox on vps (12s)"
}
```

---

## ERROR HANDLING & ROLLBACK

- Every deployment snapshots current state before applying changes
- On failure: auto-rollback to last known good, push Discord alert
- Never let one failing node cascade — isolate and continue on remaining nodes
- Log all errors to `/mnt/shanebrain-raid/shanebrain-core/logs/angel-cloud/`

---

## TECH STACK

- **Language:** Python (preferred for Pi compatibility) or Node.js
- **SSH:** Paramiko (Python) or ssh2 (Node) — key-based only, no passwords
- **Networking:** Tailscale IPs only
- **Config:** `.env` file at project root + `~/.angel-cloud/config.json`
- **Daemon:** systemd service on Linux nodes, NSSM on Windows nodes

---

## FILE STRUCTURE

```
angel-cloud-cli/
├── CLAUDE.md              ← you are here
├── .env                   ← secrets (never commit)
├── .env.example
├── README.md
├── requirements.txt
├── cli.py                 ← entry point
├── commands/
│   ├── deploy.py
│   ├── status.py
│   ├── health.py
│   ├── logs.py
│   ├── rollback.py
│   ├── mcp.py
│   └── cluster.py
├── core/
│   ├── ssh.py             ← SSH connection manager
│   ├── tailscale.py       ← node discovery
│   ├── notifications.py   ← Discord webhook
│   └── config.py
├── agents/
│   └── cluster-agent.py   ← runs on each headless node
└── services/
    └── angel-cloud-agent.service  ← systemd unit file
```

---

## CLUSTER AGENT (runs on every node)

Lightweight Python daemon that:
1. Pings Pi coordinator every 60 seconds with health report
2. Accepts task assignments from Pi via HTTP (port 9001)
3. Executes assigned tasks (inference, sync, deployment)
4. Reports results back to Pi
5. Restarts automatically via systemd if it crashes

---

## CODING RULES

- Optimize for low memory — Pi has 16GB shared with Ollama/Weaviate/Docker
- All Pi work references `/mnt/shanebrain-raid/shanebrain-core/`
- Never hardcode IPs — use config file
- Key-based SSH only — no password prompts ever
- Every function needs error handling — no bare excepts
- Short, readable functions — ADHD-friendly code
- Comment the why, not the what

---

## DO NOT

- Do NOT use MagicDNS hostnames — use Tailscale IPs
- Do NOT write outside `/mnt/shanebrain-raid/shanebrain-core/` on Pi without asking
- Do NOT add heavy dependencies — keep it lean
- Do NOT store secrets in code — use `.env`
- Do NOT block the main thread — async where possible

---

## SSH ACCESS

```bash
# Pi 5
ssh shane@100.67.120.6 -p 22

# Pulsar0100
ssh shane@100.81.70.117
```

Key auth already established between Pi and Pulsar0100.

---

## CURRENT STATUS

- [ ] Angel Cloud CLI — scaffolding needed
- [ ] Cluster agent daemon — build and deploy to each node
- [ ] Headless node config — per-laptop sleep/wake settings
- [ ] MCP discovery layer — list MCPs across cluster
- [ ] Discord webhook — integrate notifications
- [ ] Systemd service files — one per node type

---
*Last updated: March 2026 | Shane Brazelton | ShaneBrain ecosystem*
