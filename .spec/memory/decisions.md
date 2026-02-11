# Decisions

## Multi-instance: no IPC

Instances are fully independent. They share a bot token but own different groups. No shared state, no distributed locking. Filtering at handler level via `CCBOT_GROUP_ID`.

## Command tiers

- Tier 1 (bot-native): `/new`, `/resume`, `/sessions`, `/history` -- always registered
- Tier 2 (CC pass-through): auto-discovered from filesystem, refreshed periodically
- Tier 3 (contextual): `/esc`, `/kill`, `/screenshot` demoted to inline buttons

## Session resume strategy

Dead window detected when user sends message to bound-but-gone window. Recovery offers Fresh (new `claude`), Continue (`claude --continue`), Resume picker (`claude --resume <id>`).

## Topic emoji

Uses `editForumTopic(icon_custom_emoji_id=...)`. Graceful degradation: skip silently if bot lacks "Manage Topics" permission.
