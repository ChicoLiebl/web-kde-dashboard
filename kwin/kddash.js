// Persistent KWin script: pushes a snapshot of desktops + windows to the
// kddash service (org.kddash on the session bus) whenever something changes.
const SVC = "org.kddash", PATH = "/", IFACE = "org.kddash";

function snapshot() {
    const desktops = workspace.desktops.map((d, i) => ({ id: d.id, name: d.name, index: i }));
    const windows = workspace.windowList()
        .filter(w => w.normalWindow && !w.skipTaskbar)
        .map(w => ({
            id: w.internalId.toString(),
            pid: w.pid,
            cls: w.resourceClass,
            caption: w.caption,
            desktops: w.onAllDesktops ? [] : w.desktops.map(d => d.id),
            active: w === workspace.activeWindow,
            minimized: w.minimized,
        }));
    callDBus(SVC, PATH, IFACE, "Push", JSON.stringify({
        current: workspace.currentDesktop.id, desktops, windows,
    }));
}

function watch(w) {
    w.captionChanged.connect(snapshot);
    w.desktopsChanged.connect(snapshot);
    w.minimizedChanged.connect(snapshot);
}

workspace.windowList().forEach(watch);
workspace.windowAdded.connect(w => { watch(w); snapshot(); });
workspace.windowRemoved.connect(snapshot);
workspace.windowActivated.connect(snapshot);
workspace.currentDesktopChanged.connect(snapshot);
workspace.desktopsChanged.connect(snapshot);
snapshot();
