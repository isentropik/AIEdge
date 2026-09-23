// Original AIEdge policy around ESP Web Tools' existing flash operation.
// Each attempt writes the same verified image. Never resume a partial write.
export async function flashWithSpeedFallback(run, onEvent, eraseFirst) {
  let erased = false;
  for (const baudrate of [460800, 115200]) {
    let failure;
    try {
      await run(event => {
        if (event.state === 'erasing' && event.details?.done) erased = true;
        // Upstream closes its transport after this event. Wait for that cleanup
        // before retrying or letting the dialog reopen the port.
        if (event.state === 'error') { failure = event; return; }
        onEvent({...event, baudrate,
          ...(baudrate === 115200 && ['initializing','preparing'].includes(event.state)
            ? {message:'Retrying USB installation at 115,200 baud…'} : {})});
      }, baudrate, eraseFirst && !erased);
    } catch (error) {
      // An unexpected/cleanup failure is not a clean handoff to another attempt.
      onEvent({state:'error', message:'USB installation stopped. Reconnect the device and try again.',
        details:{error:'usb_recovery_failed', details:error}});
      return;
    }
    if (!failure) return;
    const cause = failure.details?.details;
    const unavailable = ['NotAllowedError','NotFoundError','InvalidStateError','SecurityError'].includes(cause?.name);
    const retryable = ['failed_initialize','write_failed'].includes(failure.details?.error);
    if (baudrate === 115200 || unavailable || !retryable) { onEvent(failure); return; }
    onEvent({state:'initializing', message:'Fast USB connection failed. Retrying at 115,200 baud…',
      baudrate:115200, details:{done:false, slowFallback:true}});
  }
}
