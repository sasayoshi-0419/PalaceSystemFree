# Agent notes（無料版）

At the **start of every conversation**, read and follow [`.cursor/skills/project-bootstrap/SKILL.md`](.cursor/skills/project-bootstrap/SKILL.md) **before** answering product questions or editing code. That skill lists: [`AGENTS.md`](AGENTS.md), [`README.md`](README.md), [`config.example.yaml`](config.example.yaml), and `LICENSE`.

Do not reconstruct the product from memory. User-facing replies are in Japanese.

## Who implements

Product code is implemented by **Composer 2.5** (including Composer 2.5 Fast). Other models follow [`.cursor/skills/plan-and-review/SKILL.md`](.cursor/skills/plan-and-review/SKILL.md): write an implementation brief, then review the diff. Do not edit `palworld_admin/`, `palworld_discord_bot/`, `packaging/`, launch scripts, or non-docs tests unless the user explicitly says to implement in this chat.

If this agent spawns an implementation subagent, set the model to `composer-2.5` only.

## This repository

This is the **free MIT** edition (`PalaceSystemFree`). Do not add Palworld official branding, PalServer.exe, or SteamCMD to any distribution. Discord is notify-only (no start/stop from Discord). Do not change `AdminPassword` / `RESTAPIEnabled` / `RESTAPIPort` from the admin UI. One `webview.start()` per process. Do not stop PalServer when the admin tool exits.

Paid-only features (Authenticode, installer, license checks, crash-restart watchdog, commercial auto-update, productized backup/restore UI) do **not** belong here.

The unsigned Windows EXE is `HomeServerAdmin.exe` (PyInstaller). Paid differentiation is a signed installer and ops extras in a separate private overlay — not the EXE wrap itself.
