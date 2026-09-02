# Connect two Windows PCs with Tailscale

Use this when FE_AIDancing runs on one PC and ComfyUI runs on a GPU PC. Tailscale gives each machine a private `100.x.x.x` address so they can reach each other without opening router ports. ComfyUI stays on `127.0.0.1:8188` on the GPU. The app PC reaches it through an SSH tunnel.

```
Browser → FE_AIDancing :8000 (app PC)
              → http://127.0.0.1:8188
                    → ssh -N gpu-comfy  (Tailscale)
                          → GPU OpenSSH :22
                                → ComfyUI 127.0.0.1:8188
```

Customers never talk to the GPU. Only this backend uses 8188.

Each machine on your tailnet gets its **own** Tailscale IPv4 (`100.x.x.x`). Those addresses are not shared and are not the same as LAN IPs (`192.168.x.x`). Read them from the machines in front of you; do not copy an IP from this doc.

| Role | How to identify it |
|---|---|
| App PC | Runs this repo on port 8000 |
| GPU PC | Runs ComfyUI; `curl http://127.0.0.1:8188/system_stats` works **on that box** |

On **each** PC:

```powershell
hostname
whoami
tailscale ip -4
tailscale status
```

- `tailscale ip -4` on the **GPU PC** is what you put in SSH `HostName`.
- `whoami` on the **GPU PC** (the part after `\`) is SSH `User`, not the computer hostname.
- If Tailscale reconnects and the IP changes, update `HostName` in SSH config.

---

## 1. Install Tailscale on both PCs

1. Download [Tailscale for Windows](https://tailscale.com/download) on **both** machines.
2. Sign in with the **same** account (same email / tailnet).
3. Leave the Tailscale icon running. Status should be Connected.

On each PC, PowerShell:

```powershell
tailscale status
```

You want both names `online`. From `tailscale status`, copy the GPU machine’s `100.x.x.x` (the row that is **not** this PC).

From the **app PC**, ping **that** GPU Tailscale IP:

```powershell
ping <GPU_TAILSCALE_IPV4>
```

Example: if `tailscale status` shows the GPU as `100.x.x.x`, ping that value. Every tailnet assigns different addresses; a number from someone else’s setup will not work.

Ping can fail if ICMP is blocked; SSH can still work. If `tailscale status` does not list the other PC, you are on different accounts or Tailscale is not running there.

Do **not** port-forward 22 or 8188 on the router. Tailscale carries the traffic.

---

## 2. GPU PC: ComfyUI on localhost

On the **GPU PC**, start ComfyUI from its install folder. Confirm locally:

```powershell
curl http://127.0.0.1:8188/system_stats
```

You want JSON (GPU name, etc.). Keep ComfyUI bound to **127.0.0.1:8188**. Do not expose 8188 to the internet.

Optional (saves VRAM for large Wan jobs):

```powershell
cd <COMFYUI_DIR>
.\venv\Scripts\python.exe main.py --listen 127.0.0.1 --port 8188 --lowvram
```

Do not use `--highvram` or `--gpu-only` unless you have spare VRAM.

---

## 3. GPU PC: OpenSSH Server

Do this on the **GPU PC**, not the app PC.

### Install

Settings → System → Optional features → **See available features** → **OpenSSH Server** → Add.

Or PowerShell **as Administrator**:

```powershell
Get-WindowsCapability -Online | Where-Object Name -like "OpenSSH.Server*"
Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0
```

Use the exact `Name` from the first command if it differs.

### Start and persist

```powershell
Start-Service sshd
Set-Service -Name sshd -StartupType Automatic
Get-Service sshd
```

`Status` must be **Running**.

### Firewall

Allow OpenSSH Server on the Tailscale adapter if Windows Firewall blocks inbound 22. Tailscale ACLs can stay default (devices in your tailnet can talk) until it works.

---

## 4. App PC: SSH key

On the **app PC**:

```powershell
Get-ChildItem $env:USERPROFILE\.ssh\*.pub
type $env:USERPROFILE\.ssh\id_ed25519_personal.pub
```

Copy the **whole single line** (`ssh-ed25519 …`). Never copy the file without `.pub`.

If that public key does not exist:

```powershell
ssh-keygen -t ed25519 -C "fe-aidancing-tunnel" -f $env:USERPROFILE\.ssh\id_ed25519_personal
type $env:USERPROFILE\.ssh\id_ed25519_personal.pub
```

---

## 5. GPU PC: authorized_keys

SSH `User` is the **Windows login** on the GPU (`whoami` after `\`), **not** the computer hostname.

On the GPU PC:

```powershell
whoami
```

Example: `HOSTNAME\alice` → `User` is `alice`.

### Non-admin user

```powershell
New-Item -ItemType Directory -Force -Path $env:USERPROFILE\.ssh | Out-Null
Set-Content -Path $env:USERPROFILE\.ssh\authorized_keys -Value "PASTE_THE_WHOLE_PUBLIC_KEY_LINE_HERE" -Encoding ascii
icacls $env:USERPROFILE\.ssh\authorized_keys /inheritance:r /grant:r "$($env:USERNAME):(R)"
```

Notepad often saves `authorized_keys.txt`. Rename it to `authorized_keys` (no extension).

### Admin user

Windows OpenSSH does **not** read `C:\Users\<User>\.ssh\authorized_keys` for Administrators. Put the key here instead:

`C:\ProgramData\ssh\administrators_authorized_keys`

```powershell
Set-Content -Path C:\ProgramData\ssh\administrators_authorized_keys -Value "PASTE_THE_WHOLE_PUBLIC_KEY_LINE_HERE" -Encoding ascii
icacls C:\ProgramData\ssh\administrators_authorized_keys /inheritance:r /grant "Administrators:F" /grant "SYSTEM:F"
Restart-Service sshd
```

The file must contain the real `ssh-ed25519 …` line, not the word `PASTE_KEY`.

---

## 6. App PC: SSH config

Edit `%USERPROFILE%\.ssh\config` on the **app PC**. Keep any existing `Host github-personal` (or other) blocks. **Add** (do not replace):

```
Host gpu-comfy
  HostName <GPU_TAILSCALE_IPV4>
  User <GPU_WINDOWS_LOGIN>
  IdentityFile ~/.ssh/id_ed25519_personal
  IdentitiesOnly yes
  LocalForward 8188 127.0.0.1:8188
  ServerAliveInterval 30
  ServerAliveCountMax 3
  ExitOnForwardFailure yes
```

- `HostName` — output of `tailscale ip -4` on the **GPU PC** (a `100.x.x.x` address unique to that machine).
- `User` — GPU Windows login from `whoami` on the GPU PC, not the hostname.

`.env` on the app stays:

```env
COMFYUI_BASE_URL=http://127.0.0.1:8188
```

The tunnel makes this PC’s 8188 equal ComfyUI on the GPU.

---

## 7. Connect

On the **app PC**:

```powershell
ssh gpu-comfy
```

First connect: type `yes` for the host key. You should land on the GPU with no password. Then:

```text
exit
```

Tunnel only (leave this window open):

```powershell
ssh -N gpu-comfy
```

Ctrl+C closes the tunnel.

In a **second** terminal on the app PC:

```powershell
curl http://127.0.0.1:8188/system_stats
```

Same GPU JSON as on the GPU PC means the path works. Then start the app:

```powershell
cd <FE_AIDANCING_DIR>
.\.venv\Scripts\activate
python main.py
```

---

## 8. Daily checklist

1. Tailscale connected on both PCs (`tailscale status`).
2. ComfyUI running on the GPU (`curl http://127.0.0.1:8188/system_stats` there).
3. `sshd` Running on the GPU.
4. App PC: `ssh -N gpu-comfy` left open.
5. App PC: `curl http://127.0.0.1:8188/system_stats` then `python main.py`.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| GPU missing from `tailscale status` | Same Tailscale account; app running on both PCs |
| `ssh: connect to host 100.x.x.x port 22` fails | `sshd` Running; firewall; `HostName` is the GPU IP |
| Password prompt / public key denied | Wrong `User`; for an Administrator login use `administrators_authorized_keys`; `icacls` on that file; `IdentitiesOnly yes` + matching `IdentityFile` |
| `curl :8188` works on GPU, fails on app | Tunnel not running (`ssh -N gpu-comfy`); another process already bound to 8188 on the app PC |
| `No route exists for name "jobs_page"` | Unrelated to Tailscale; FE route bug |
| WSL `.bat` that POSTs to a WSL IP `:8188/free` | Wrong machine. ComfyUI is Windows `127.0.0.1:8188`. Use `curl` to that address, or restart ComfyUI after OOM |

Free VRAM on the real ComfyUI (GPU, or app PC while the tunnel is up):

```powershell
curl -X POST http://127.0.0.1:8188/free -H "Content-Type: application/json" -d "{\"unload_models\":true,\"free_memory\":true}"
```

After a hard CUDA OOM (`Free: 0 bytes`), quit ComfyUI fully and start it again. `/free` is not enough.

---

## Optional: skip SSH, talk to Tailscale IP

If you bind ComfyUI to the Tailscale interface (or `--listen 0.0.0.0` plus a firewall that only allows the tailnet), the app can use the GPU’s **current** Tailscale IPv4:

```env
COMFYUI_BASE_URL=http://<GPU_TAILSCALE_IPV4>:8188
```

Get `<GPU_TAILSCALE_IPV4>` with `tailscale ip -4` on the GPU PC. Do not reuse an address from another machine or another tailnet.

This project’s working setup is the SSH tunnel instead, so 8188 never leaves localhost on the GPU.
