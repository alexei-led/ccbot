# Inter-Agent Messaging — Test Specification

## Unit Tests

### mailbox

| Name                                   | Scenario               | Expected                          |
| -------------------------------------- | ---------------------- | --------------------------------- |
| `test_mailbox_send_creates_file`       | Send to peer           | File with timestamp prefix exists |
| `test_mailbox_inbox_lists_sorted`      | 3 messages             | Returned oldest-first             |
| `test_mailbox_read_marks_read`         | Read one               | File moved to read/ or flag set   |
| `test_mailbox_reply_links_to_original` | Reply with ref         | `in_reply_to` field set           |
| `test_mailbox_broadcast_fanout`        | Broadcast to 3 peers   | 3 files created                   |
| `test_mailbox_ttl_expiration`          | Message older than TTL | Swept on next sweep               |
| `test_mailbox_atomic_write`            | Interrupt mid-write    | No partial file visible           |
| `test_mailbox_id_migration_old_to_new` | Old-format filename    | Renamed to new format             |

### msg_discovery

| Name                               | Scenario         | Expected                   |
| ---------------------------------- | ---------------- | -------------------------- |
| `test_list_peers_from_session_map` | 3 active windows | Returns 3 peers            |
| `test_find_peer_by_team`           | Team filter      | Only matching peers        |
| `test_find_peer_by_task`           | Task substring   | Only matching peers        |
| `test_self_declared_task_overlay`  | Set task, list   | Task visible in peer entry |

### msg_delivery / msg_broker

| Name                                    | Scenario                 | Expected                             |
| --------------------------------------- | ------------------------ | ------------------------------------ |
| `test_rate_limit_blocks_over_threshold` | 11 messages in 5m window | 11th rejected                        |
| `test_loop_detection_pauses_pair`       | A→B→A→B rapid            | Pair paused with alert               |
| `test_broker_injects_into_idle_window`  | Idle pane                | `send_keys` called                   |
| `test_broker_skips_busy_window`         | Running agent            | Skipped                              |
| `test_broker_shell_window_inbox_only`   | Shell provider           | Not injected, inbox still accessible |

### msg_spawn

| Name                                    | Scenario                            | Expected                         |
| --------------------------------------- | ----------------------------------- | -------------------------------- |
| `test_spawn_request_creation`           | `msg spawn` CLI                     | File in spawn_requests/          |
| `test_spawn_approval_creates_topic`     | User taps Approve                   | `create_topic_for_window` called |
| `test_spawn_rejection_discards_request` | User taps Reject                    | File removed                     |
| `test_spawn_rate_limit`                 | 4 spawns from one window in an hour | 4th blocked                      |
| `test_spawn_timeout`                    | Approval not received in time       | Request expired                  |

## Integration Contract Tests

| Name                                            | Scenario                             | Expected                                        |
| ----------------------------------------------- | ------------------------------------ | ----------------------------------------------- |
| `test_round_trip_send_inbox_read`               | A sends to B, B reads                | Message lifecycle complete                      |
| `test_broadcast_telegram_notification_grouping` | Broadcast to 3                       | Single grouped notification per recipient topic |
| `test_spawn_telegram_approval_flow`             | Request → keyboard → approve → topic | End-to-end works                                |
| `test_msg_skill_installed_for_claude`           | Create Claude window                 | Skill file appears in claude config dir         |

## Boundary Tests

| Name                                     | Scenario                           | Expected                                |
| ---------------------------------------- | ---------------------------------- | --------------------------------------- |
| `test_wait_deadlock_prevention`          | A `--wait` to B, B `--wait` to A   | Times out instead of hanging            |
| `test_mailbox_concurrent_writes`         | Two bot instances write same dir   | Both files persisted (timestamp-unique) |
| `test_malformed_message_file`            | Corrupted JSON                     | Skipped, logged                         |
| `test_peer_registration_no_window_state` | Register before tmux window exists | Stored as pending                       |

## Behavior Tests

| Name                                          | Scenario                                           | Expected                                |
| --------------------------------------------- | -------------------------------------------------- | --------------------------------------- |
| `test_scenario_agent_to_agent_ask_and_answer` | Agent A sends `--wait` to B, B replies, A receives | Full round-trip                         |
| `test_scenario_telegram_reply_edits_in_place` | Reply via Telegram                                 | Original message edited, not duplicated |
| `test_scenario_loop_alert_and_resume`         | Loop detected, user taps Resume                    | Delivery resumes                        |
