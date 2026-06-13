# Runlogger Adapter - Hermes

Mode: inspect/recommend first.

## Evidence
- Inspect agent logs, notification/recommendation logs, bridge manifests, automation queues, and recent terminal output.
- Check BrainCore registry links when routing or connected-app behavior is involved.
- Use read-only queue and config inspection first.

## Checks
- Discover verification commands from project scripts before running them.
- For high-confidence fixes, run the narrowest available test or smoke check.

## Forbidden
- Do not send notifications, run live automations, delete queue items, commit, push, or deploy unless explicitly requested.
