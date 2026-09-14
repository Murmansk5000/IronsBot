# Addressed Input Routing

Status: in progress

## Goal

OneBot and QQ Official must share the same decision order for input addressed to the
bot. Platform adapters normalize input and capabilities; business commands remain
owned by the shared command catalog.

## Decision order

1. Convert the platform event to `MessageInputContext`.
2. Reject messages blocked by actor or conversation policy.
3. Let the command catalog recognize explicit command syntax before feature and
   audience admission.
4. Dispatch an available command through its registered operation.
5. Never reinterpret recognized but unavailable command syntax as AI chat.
6. Route unclaimed addressed text to AI when AI chat is available.
7. Otherwise return the shared direct-command hint, rate-limited by actor and
   conversation.

## Behavior matrix

| Input | AI available | Result |
| --- | --- | --- |
| Valid explicit command | Either | Execute the command |
| Recognized command unavailable to this actor or platform | Either | Do not send it to AI |
| Unclaimed group mention | Yes | AI chat |
| Unclaimed private text | Yes | AI chat |
| Empty addressed input | Yes | AI prompt |
| Empty or unknown group mention | No | Rate-limited command hint |
| Repeated unknown group mention | No | Silent after the shared limit |
| Blocked actor or conversation | Either | Silent |
| Ordinary group text without a mention | Either | No AI chat |

## Delivery slices

1. Command precedence and shared addressed-input hint limiter.
2. One AI decision path for chat and configured intent actions.
3. Cross-platform behavior tests for commands, AI fallback, disabled features,
   blacklist policy, and contextual commands.

The old OneBot pre-command mention guard and its separate cooldown configuration
are removed rather than retained as a compatibility path.
