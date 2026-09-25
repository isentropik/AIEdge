# When consumption tracking cannot start

The diagnostic reason `accounting_unavailable` means the saved settings or
consumption checkpoint could not be activated. Check `persistence_state` for the
cause. It is separate from `invalid_bounds`, which indicates invalid calculation
bounds.

| Persistence state | Meaning |
| --- | --- |
| `settings_unavailable` | Saved tracking settings could not be read or recovered. |
| `incompatible` | The saved checkpoint does not match the active reader, calibration or assumptions, or fails semantic validation. |
| `corrupt` | No intact checkpoint copy could be loaded. |
| `io_error` | A checkpoint could not be read from storage. |
| `conflict` | Checkpoint copies contradict each other. |

The firmware preserves these files and refuses to publish a new consumption
estimate from them. It does not erase the history, silently choose an older
compatible copy over a newer incompatible one, or assume zero consumption across
the gap. Repeated readings do not repeatedly attempt uncertain recovery writes.

Preserve the original files before attempting recovery. An incompatible reader
update may require restoring its previous matching bundle or an explicit,
reviewed new-baseline procedure. There is currently no automatic migration or
one-click checkpoint reset. Changing the maximum-flow setting is not a repair for
a damaged or incompatible checkpoint.

Host regression checks cover changed model/calibration identities, corrupt
checkpoint bytes, unreadable settings, serialized rejection reasons, and exact
preservation of stored bytes. They do not establish physical SD recovery or live
MQTT delivery. The diagnostic correction is source-tested; its next device
candidate is `aiedge-accounting-status-01`.
