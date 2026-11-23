// Claude Desktops: the kddash Desktops screen in a panel popup.
//
// The panel shows a crab with a badge counting the Claude sessions that need you (yellow, blinking
// while one is waiting on a permission or question). Clicking it opens the dashboard page itself
// (served by kddash.py, ?view=panel), so it looks and works like the tablet: click a card to go to
// that desktop or window, right-click a desktop to mark sessions idle or open a session there.
import QtQuick
import QtQuick.Layouts
import QtWebEngine
import org.kde.plasma.plasmoid
import org.kde.plasma.components as PlasmaComponents3
import org.kde.plasma.plasma5support as P5Support
import org.kde.kirigami as Kirigami

PlasmoidItem {
    id: root

    readonly property string baseUrl: (Plasmoid.configuration.url || "http://127.0.0.1:8765").replace(/\/+$/, "")
    property string token: ""
    property bool online: false
    property int alerts: 0     // done or blocked, not marked idle (isAlert in static/index.html)
    property int blocked: 0    // waiting on you mid-turn: permission, question
    property int working: 0

    preferredRepresentation: compactRepresentation
    toolTipMainText: i18n("Claude Desktops")
    toolTipSubText: !token ? i18n("No kddash token in ~/.config/kddash/token")
        : !online ? i18n("kddash isn't answering at %1", baseUrl)
        : (alerts || working) ? [alerts ? i18n("%1 need you", alerts) : "", working ? i18n("%1 working", working) : ""]
            .filter(s => s).join(" · ")
        : i18n("No Claude session needs you")

    // ---- token: the same file the tablet URL comes from
    P5Support.DataSource {
        id: exec
        engine: "executable"
        onNewData: (source, data) => {
            root.token = (data.stdout || "").trim()
            disconnectSource(source)
        }
    }
    function readToken() { exec.connectSource('cat "${XDG_CONFIG_HOME:-$HOME/.config}/kddash/token"') }
    Component.onCompleted: readToken()

    // ---- status for the panel icon
    function poll() {
        if (!token) { readToken(); return }
        const xhr = new XMLHttpRequest()
        xhr.onreadystatechange = () => {
            if (xhr.readyState !== XMLHttpRequest.DONE) return
            if (xhr.status !== 200) {
                root.online = false
                if (xhr.status === 403) readToken()  // kddash made a new token
                return
            }
            let s
            try { s = JSON.parse(xhr.responseText) } catch (e) { root.online = false; return }
            let a = 0, b = 0, w = 0
            for (const win of s.windows || [])
                for (const c of win.claude || []) {
                    if (!c.snoozed && (c.status === "done" || c.status === "blocked")) a++
                    if (!c.snoozed && c.status === "blocked") b++
                    if (c.status === "working") w++
                }
            root.online = true
            root.alerts = a; root.blocked = b; root.working = w
        }
        xhr.open("GET", baseUrl + "/api/state?t=" + encodeURIComponent(token))
        xhr.send()
    }
    Timer { interval: 2000; running: true; repeat: true; triggeredOnStart: true; onTriggered: root.poll() }

    compactRepresentation: MouseArea {
        id: compact
        Layout.minimumWidth: crab.width + (badge.visible ? badge.width / 2 : 0)
        Layout.preferredWidth: Layout.minimumWidth
        hoverEnabled: true
        onClicked: root.expanded = !root.expanded

        property bool blinkOn: true
        Timer {
            interval: 600; repeat: true
            running: root.blocked > 0
            onTriggered: compact.blinkOn = !compact.blinkOn
            onRunningChanged: compact.blinkOn = true
        }

        Image {
            id: crab
            anchors.verticalCenter: parent.verticalCenter
            height: Math.round(parent.height * 0.62)
            width: Math.round(height * 14 / 8)
            source: Qt.resolvedUrl("../icons/crab.svg")
            sourceSize: Qt.size(width * 2, height * 2)
            smooth: false
            opacity: root.online ? 1 : 0.45
        }
        Rectangle {
            id: badge
            visible: root.alerts > 0
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.topMargin: Math.round(parent.height * 0.08)
            height: Math.round(parent.height * 0.5)
            width: Math.max(height, count.implicitWidth + height * 0.5)
            radius: height / 2
            color: "#ffcc00"
            opacity: compact.blinkOn ? 1 : 0.3
            PlasmaComponents3.Label {
                id: count
                anchors.centerIn: parent
                text: root.alerts
                color: "#1a1400"
                font.bold: true
                font.pixelSize: Math.round(badge.height * 0.78)
            }
        }
        Rectangle {  // something is working and nothing needs you
            visible: root.alerts === 0 && root.working > 0
            anchors.right: crab.right
            anchors.top: parent.top
            anchors.topMargin: Math.round(parent.height * 0.12)
            width: Math.round(parent.height * 0.22); height: width; radius: width / 2
            color: "#4c8dff"
        }
    }

    fullRepresentation: Item {
        Layout.preferredWidth: Kirigami.Units.gridUnit * 60
        Layout.preferredHeight: Kirigami.Units.gridUnit * 38
        Layout.minimumWidth: Kirigami.Units.gridUnit * 30
        Layout.minimumHeight: Kirigami.Units.gridUnit * 20

        WebEngineProfilePrototype {
            id: profile
            storageName: "kddash-panel"  // keeps the page's own settings (Even/Dynamic tiles, tab)
        }
        WebEngineView {
            id: web
            anchors.fill: parent
            visible: !!root.token
            profile: profile.instance()
            backgroundColor: "#0f1115"
            url: root.token ? root.baseUrl + "/?t=" + encodeURIComponent(root.token) + "&view=panel" : ""
            // The page handles right-click itself (the desktop sheet); no Chromium menu.
            onContextMenuRequested: request => { request.accepted = true }
            onLoadingChanged: info => { if (info.status === WebEngineView.LoadFailedStatus) retry.restart() }
        }
        Timer { id: retry; interval: 5000; onTriggered: web.reload() }
        PlasmaComponents3.Label {
            anchors.centerIn: parent
            visible: !root.token
            text: i18n("kddash isn't set up: no token in ~/.config/kddash/token")
        }
    }
}
