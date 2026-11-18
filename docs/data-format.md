# Data format

What the recorder expects on the broker: the shape of a topic, the shape
of a payload, and what it does with a message that has neither. The
parser is the `swim_project.model` module;
where the readings end up is in [database.md](database.md).

One MQTT message carries one reading: one value of one parameter of one
device at one instant.

## Topic

```text
<location...>/<kind>/<device_id>/<parameter>
```

The recorder reads a topic from the right. The last three segments are
fixed; everything before them is the device's location.

| Segment | Meaning | Rule |
| :--- | :--- | :--- |
| `location...` | Where the device is, from the widest place to the narrowest | One or more segments, any names |
| `kind` | `S` for a sensor, `A` for an actuator | Exactly `S` or `A` |
| `device_id` | The device's identifier, unique on the broker | Any non-empty segment |
| `parameter` | What the reading measures or sets | Any non-empty segment |

A topic therefore has at least four segments, and none may be empty (no
leading, trailing or doubled `/`). The recorder gives the location
segments no names: one deployment may use `site/building/floor/room/zone`,
another just `lab`. Keep the depth the same across a deployment so that
queries can address a level by position (see
[database.md](database.md#querying-by-location)).

### Topic examples

| Topic | location | kind | device_id | parameter |
| :--- | :--- | :--- | :--- | :--- |
| `site-a/building-1/room/101/desk-1/S/TRH-0001/temperature` | `{site-a,building-1,room,101,desk-1}` | `S` | `TRH-0001` | `temperature` |
| `site-a/building-1/room/101/desk-1/S/TRH-0001/relative_humidity` | `{site-a,building-1,room,101,desk-1}` | `S` | `TRH-0001` | `relative_humidity` |
| `site-a/building-1/room/101/ahu-1/A/VLV-0007/position` | `{site-a,building-1,room,101,ahu-1}` | `A` | `VLV-0007` | `position` |
| `lab/S/CO2-0003/co2` | `{lab}` | `S` | `CO2-0003` | `co2` |

### Subscribing

The recorder subscribes to the filters in `[mqtt] topics` of the
config file, one per line; `record --topic` replaces them for one run
and may be repeated. Filters are standard MQTT: `+` matches one segment
and `#` any number of trailing ones.

| Filter | Receives |
| :--- | :--- |
| `site-a/#` | Every device anywhere under `site-a` |
| `site-a/building-1/room/101/+/S/+/+` | Every sensor parameter in room 101 (five-segment location) |
| `site-a/building-1/room/101/+/S/+/temperature` | Temperatures only |
| `site-a/building-1/room/101/desk-1/#` | Everything at `desk-1` |

A filter can only match topics the broker account may read. Messages on
a matching topic that break the format are counted as skipped, never
stored.

## Payload

A UTF-8 JSON object with three required fields:

| Field | Type | Meaning |
| :--- | :--- | :--- |
| `value` | JSON number | The reading. An integer is stored as a float. `true`/`false` are refused. |
| `ts` | string, ISO 8601 with a UTC offset | When the device took the reading, by the device's clock. Fractional seconds and `Z` are accepted. |
| `unit` | string | The unit of `value`, for example `Cel`, `%RH`, `ppm`, `%` |

Any other field is ignored and not stored.

The units seen so far follow the UCUM case-sensitive codes (`Cel` for
degrees Celsius, `%` for percent); `%RH` is a convention for relative
humidity, not a UCUM code. The recorder stores `unit` as given and does
not check it.

### Payload examples

A temperature, stamped in the device's local time (UTC+8):

```json
{"value": 23.98, "ts": "2026-11-18T16:31:23+08:00", "unit": "Cel"}
```

The relative humidity from the same device at the same instant, on the
`.../relative_humidity` topic:

```json
{"value": 55.56, "ts": "2026-11-18T16:31:23+08:00", "unit": "%RH"}
```

An actuator position in UTC with milliseconds; `source` is ignored:

```json
{"value": 40, "ts": "2026-11-18T08:31:23.250Z", "unit": "%", "source": "bms"}
```

Publishing a test reading to a local broker with mosquitto:

```bash
mosquitto_pub -h 127.0.0.1 -p 1883 \
    -t 'site-a/building-1/room/101/desk-1/S/TRH-0001/temperature' \
    -m '{"value": 23.98, "ts": "2026-11-18T16:31:23+08:00", "unit": "Cel"}'
```

Point the recorder at it with `tls=false` in `[mqtt]`.

## Skipped messages

A message whose topic or payload breaks the rules above is not stored.
It is counted under its reason in the live table caption and the summary
printed on exit. The recorder keeps running.

| Example topic or payload | Reason counted |
| :--- | :--- |
| `S/TRH-0001/temperature` | `topic has fewer than 4 segments or an empty one` |
| `site-a//desk-1/S/TRH-0001/temperature` | `topic has fewer than 4 segments or an empty one` |
| `site-a/desk-1/X/TRH-0001/temperature` | `topic's sensor-or-actuator segment is neither S nor A` |
| `23.98` or `[23.98]` | `payload is not a JSON object` |
| `{"value": 23.98,` (truncated), or bytes that are not UTF-8 | `payload is not UTF-8 JSON` |
| `{"value": "23.98", "ts": "...", "unit": "Cel"}` | `payload value is not a number` |
| `{"value": true, "ts": "...", "unit": "Cel"}` | `payload value is not a number` |
| `{"value": 23.98, "ts": "..."}` | `payload unit is not a string` |
| `{"value": 23.98, "unit": "Cel"}` | `payload has no ISO 8601 ts` |
| `{"value": 23.98, "ts": 1763454683, "unit": "Cel"}` | `payload has no ISO 8601 ts` |
| `{"value": 23.98, "ts": "2026-11-18T16:31:23", "unit": "Cel"}` | `payload ts has no UTC offset` |

The topic is checked first, so a message with both a bad topic and a bad
payload is counted under the topic reason.

## Timestamps and duplicates

`ts` is the device's clock, not the recorder's. The recorder keeps both:
`ts` as `measured_at` and its own clock on arrival as `received_at`.
The difference is worth watching. One source observed in November 2026
stamped its readings a steady 318 to 322 seconds behind the recorder's
clock, which was mostly clock offset rather than network delay.

A reading is identified by device, parameter and `ts`. A second message
with the same three is ignored, even when its value differs, so a
redelivered message is stored once. A device that sends two readings
within the same second, at whole-second resolution, loses the second.

## Accepted today, possibly not wanted

The recorder currently accepts, and stores as given:

- `NaN`, `Infinity` and `-Infinity` as `value` (Python's JSON parser reads them);
- an empty string as `unit`;
- a `type` field such as `"prediction"` or `"simulation"`, which is
  ignored, so a predicted value is stored like a measured one.
