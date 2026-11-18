# Device location is a variable-depth array

Supersedes the `device` columns of
[ADR 0001](0001-tables-mirror-topic-hierarchy.md); the `reading` table
and the rest of 0001 stand.

A topic is read from the right: the last three segments are the kind
(`S` or `A`), the device id and the parameter, and every segment before
them is the device's location. `device` stores the location as one
`text[]` column, `location`, in topic order, instead of the five named
columns `project`, `building`, `level`, `unit` and `area`.

## Why

- The recorder accepted only 8-segment topics, so a site that names its
  locations with more or fewer levels had every message skipped.
- The column names fitted one deployment's naming scheme, and not even
  that one: its `level` segment held `room` and its `unit` segment held
  a room number.
- The names carried no meaning the recorder used; it only stored them.

## Considered options

- **Keep eight segments, rename the columns neutrally** (`site`,
  `building`, `space_type`, `space`, `zone`). Rejected: still rejects
  every other depth.
- **The location as one `text` path joined with `/`.** Rejected: prefix
  and per-level queries then need string functions; an array supports
  `location[1:4] = ARRAY[...]` and `'x' = ANY (location)` directly.

## Consequences

- A query cannot name a level (`area`); it addresses it by position
  (`location[5]`) or as the last element
  (`location[cardinality(location)]`). This assumes a deployment keeps
  one depth, which the recorder does not enforce.
- The change alters an existing table. `init-db --force` migrates a
  database created with the five named columns in place, copying the five
  columns into `location` in topic order and keeping every row.
