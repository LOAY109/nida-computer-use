# Nida Computer Use — Strict Always-On Visual & Voice Rules

When the user invokes `/nida-computer-use` or asks to control their PC:

1. **REAL VISUAL DESKTOP CONTROL ONLY**: NEVER bypass desktop automation with background CMD/PowerShell scripts. Drive the user's real Windows screen visibly using `nida-desktop` MCP tools (`hud_launch`, `screen_capture`, `mouse_click`, `mouse_move`, `keyboard_type`, `browser_open_real`, `ui_tree`, `plan_run`).
2. **USER'S REAL BROWSER (CHROME) BY DEFAULT**: NEVER use Antigravity's built-in IDE browser unless the user explicitly asks to use Antigravity's own browser. Always open web pages and email in the user's real active browser or Google Chrome via `browser_open_real`.
3. **FLOATING ARABIC HUD FIRST**: Always call `hud_launch` at the start of every task so the Always-On-Top Arabic control window is visible on the user's main screen.
4. **ARABIC VOICE FIRST**: Use `voice_speak` to announce progress aloud and `voice_ask` whenever waiting for a user decision instead of silently waiting in text chat.
5. **INSTANT STOP RESPECT**: Immediately halt all actions if any tool returns `stopped: true`, and immediately follow any `user_hud_instructions`.
