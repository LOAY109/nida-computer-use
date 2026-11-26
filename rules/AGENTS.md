# Nida Computer Use — Always-On Personal Rules

When executing desktop automation tasks using the `nida-desktop` MCP server:

- Always keep the Floating Arabic Control HUD active (`hud_launch`) so the user can see live actions and trigger Emergency Stop at any moment.
- Communicate progress and decision checkpoints aloud in natural Arabic using `voice_speak` and `voice_ask` instead of leaving the user waiting silently in text chat.
- Respect `stopped: true` immediately if the user hits Stop in the HUD or presses `Ctrl+Shift+X` / double-`Esc`.
- Check and follow any live `user_hud_instructions` returned by tool calls.
- Operate in Unrestricted Personal Mode for the user's own local Windows apps, browser, email, files, and shell commands.
