# Running identity after restart

The managed update status now reports `running_bundle_id` and
`running_bundle_verified` from the immutable startup selection. A rejected or
legacy selection does not expose an identity as verified. The update page shows
this running identity separately from a staged or selected update, including
after the in-memory update job resets during reboot. Startup bundle verification
checks the firmware/asset contract; it is not reading-accuracy validation,
boot-health acceptance, or proof of rollback recovery.

Actual-handler host checks cover selected, rejected and legacy selections;
29 client workflow cases cover reporting plus the existing update gates.
The HTTP, scheduling and flash portions remain substituted in these tests.
This reporting change has not yet been installed on the test board.
