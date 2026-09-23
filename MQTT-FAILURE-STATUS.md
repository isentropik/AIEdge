# MQTT publication failure handling

September 22 local implementation: system and per-sequence publications now
require all attempted topic calls to succeed. Later success cannot erase earlier
failure. The wrapper reports suppressed sends as failures and treats all negative
client publish return codes as rejection. Its existing bounded two-attempt policy
is preserved; no delivery guarantee is inferred from client acceptance.

The controller ends a failed MQTT stage with `MQTT publication failed`, without
rerunning capture/postprocessing or rebooting. Local stage timing records failure.
A failed broker cannot reliably receive its own failure notification. Retained
value freshness and downstream HA availability still need integration.

Host tests inject failure at every system/reading topic, disconnected operation,
negative return codes, same-round suppression, next-round recovery and controller
failure behavior. Tests pass, and the ESP32 build passes. Real broker delivery
and outage recovery have not been tested. Candidate package B predates this fix.

The user added OTA updates to the objective. Existing `server_ota.cpp` uses ESP
OTA partitions and has a boot-validation path; compatibility, failure rollback,
web/model bundle consistency and recovery artifacts require an explicit audit
before proposing a live update. No update or restart has been performed.
