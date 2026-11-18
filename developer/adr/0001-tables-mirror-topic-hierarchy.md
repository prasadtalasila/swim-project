# Tables mirror the topic hierarchy: a device table and a typed reading table

Status: the `device` columns are superseded by
[ADR 0002](0002-device-location-is-a-variable-depth-array.md); the rest
stands.

A topic's first seven segments name a device and its place in the
building (`project/building/level/unit/area/S-or-A/device_id`); the
eighth names the measured parameter. `device` holds the seven segments
once per device; `reading` holds one row per message with the parameter,
the payload's `value`, `unit` and `ts` as typed columns, and the time the
recorder received it. The key `(device_id, parameter, measured_at)` makes
redelivered messages harmless (`ON CONFLICT DO NOTHING`).

## Considered Options

- **One wide table with all eight segments per reading.** Rejected: it
  repeats seven segments on every row of a stream that sends ten messages
  every three seconds.
- **A column per topic (temperature, relative_humidity, ...).** Rejected:
  a new parameter would need a schema change, and parameters arrive in
  separate messages, so rows would be sparse.
- **The raw payload as `jsonb`.** Rejected: every payload observed on the
  broker has the same `value`/`ts`/`unit` shape, and typed columns make
  range queries and indexes simple. A payload of another shape is skipped
  and counted rather than stored.

A device keeps the hierarchy it was first seen with; a device moved to
another area would need its `device` row updated by hand.
