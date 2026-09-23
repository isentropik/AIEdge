/* One request at a time, with only the newest unsent slider value retained. */
function createPreviewSender(send, report, schedule = setTimeout, cancel = clearTimeout) {
    let pending = null, timer = null, running = false;
    let idleWaiters = [];
    async function flush() {
        timer = null;
        if (running || pending === null) return;
        const value = pending;
        pending = null;
        running = true;
        try {
            await send(value);
            report("Queued for the next preview frame. Not saved.");
        } catch (error) {
            report("Brightness update failed: " + error.message + ". Move the slider to retry.");
        } finally {
            running = false;
            if (pending !== null) timer = schedule(flush, 150);
            else { idleWaiters.forEach(resolve => resolve()); idleWaiters = []; }
        }
    }
    function queue(value) {
        if (!Number.isInteger(value) || value < 0 || value > 100) return;
        pending = value;
        if (timer !== null) cancel(timer);
        timer = schedule(flush, 150);
    }
    queue.drain = () => {
        if (!running && pending === null) return Promise.resolve();
        return new Promise(resolve => idleWaiters.push(resolve));
    };
    return queue;
}

if (typeof module !== "undefined") module.exports = { createPreviewSender };
if (typeof document !== "undefined") {
    const slider = document.getElementById("intensity");
    const value = document.getElementById("value");
    const status = document.getElementById("status");
    const preview = document.getElementById("preview");
    const save = document.getElementById("save");
    const light = new URLSearchParams(location.search).get("flashlight") === "true";
    const report = text => { status.textContent = text; };
    async function request(url, method = "GET") {
        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), 3000);
        try {
            const response = await fetch(url, { method, signal: controller.signal, cache: "no-store" });
            if (!response.ok) throw new Error("HTTP " + response.status);
            return await response.json();
        } catch (error) {
            if (controller.signal.aborted) throw new Error("request timed out");
            throw error;
        } finally { clearTimeout(timeout); }
    }
    const queue = createPreviewSender(
        intensity => request("/stream_intensity?value=" + intensity, "POST"), report);
    save.addEventListener("click", async () => {
        save.disabled = slider.disabled = true;
        document.getElementById("reconnect").disabled = true;
        const intensity = Number(slider.value);
        try {
            await queue.drain();
            report("Saving capture intensity…");
            const result = await request("/stream_intensity/save?value=" + intensity, "POST");
            if (!result.saved || !result.active) throw new Error("save was not confirmed");
            report(result.cleanup_pending ?
                "Saved and active for captures. Journal cleanup is pending; inspect before another save." :
                "Saved and active for captures. No restart needed.");
        } catch (error) {
            report("Save not confirmed: " + error.message + ". Do not assume the old value is still saved; verify before retrying.");
        } finally {
            save.disabled = slider.disabled = false;
            document.getElementById("reconnect").disabled = false;
        }
    });
    slider.addEventListener("input", () => {
        value.textContent = slider.value;
        report("Waiting to send preview intensity…");
        queue(Number(slider.value));
    });
    let connecting = false;
    async function connect() {
        if (connecting) return;
        connecting = true;
        slider.disabled = true;
        try {
            const settings = await request("/stream_intensity");
            slider.value = light ? settings.configured : 0;
            value.textContent = slider.value;
            preview.src = "/stream?flashlight=" + light + "&t=" + Date.now();
            slider.disabled = false;
            save.disabled = false;
            report("Preview controls ready. Changes are temporary.");
        } catch (error) { report("Cannot start preview: " + error.message + ". Use Reconnect preview to retry."); }
        finally { connecting = false; }
    }
    preview.addEventListener("error", () => report("Preview stopped or camera is busy. Use Reconnect preview to retry."));
    document.getElementById("reconnect").addEventListener("click", connect);
    connect();
}
