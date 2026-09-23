# Configuration

Start in SetupMode. Configure camera orientation, stable illumination, alignment markers and ROIs before enabling recognition. Changing exposure, perspective or crops invalidates a prior accuracy claim.

## Lighting

Choose the actual LED type, pixel count and byte order. RGBW's dedicated white channel differs from RGB mixed white. Start at zero master intensity, increase gradually and check exposure. Verify all pixels and off behavior. See [lighting implementation notes](../LIGHTING-PORT-STATUS.md).

## Recognition

The polar path uses frozen model and geometry identities, with separate needle/dial geometry. It is meter-specific, not a universal drop-in model. See [polar configuration](../POLAR-CONFIGURATION.md) and [runtime validation](../POLAR-RUNTIME-VALIDATION.md).

## Volume and flow

Raw positions and physical volume are separate. Configure direction and significance for the actual meter. The development meter has a 5 ft³ secondary wheel and 1,000 ft³ per last main-dial revolution: 20 secondary revolutions per numbered step, 200 per main revolution. These are not universal constants.

Monotonicity applies to converted cumulative volume. Dial rollover from 9.9 to 0.0 can be normal forward movement. Endpoint positions cannot reveal missed whole wheel rotations; ambiguous intervals stay explicit. See [accounting](../METER-ACCOUNTING.md).

## Integrations

Configure MQTT/HA after validating readings. Optional image archival needs a compatible HTTP(S) receiver; a NAS SMB share alone is not that protocol. Archival is disabled by default. See [remote storage](../REMOTE-IMAGE-STORAGE.md).

Settings may apply immediately, at a safe cycle boundary, or after reinitialization/restart. Check active/pending/failed status rather than assuming a saved file is active. See [configuration activation](../CONFIG-SAVE-STATUS.md).
