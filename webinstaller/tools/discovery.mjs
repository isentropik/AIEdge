// AIEdge USB discovery recovery. Never writes firmware or Wi-Fi credentials.
export async function discoverWithRecovery({connect, reset, pause, status, isPortBusy, initialTimeout = 1500}) {
  try { return await connect(initialTimeout); }
  catch (error) {
    if (isPortBusy(error)) throw error;
    status('Restarting board for Wi-Fi setup');
    await reset();
    // Let the loader finish SD/Wi-Fi startup before asking again.
    await pause(2500);
    status('Detecting Wi-Fi setup');
    // Exactly one retry. A broken device must not enter a reset loop.
    return await connect(30000);
  }
}
