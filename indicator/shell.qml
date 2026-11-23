// Origin marker for mouse-autoscroll, like Windows' autoscroll icon.
// Listens to the daemon's state socket ($XDG_RUNTIME_DIR/mouse-autoscroll/state.sock,
// JSON lines {"state": "idle|scrolling|latched", "x", "y"}) and draws a small
// click-through circle at the origin. Separate process: if this breaks, scrolling doesn't.
// Run by mouse-autoscroll-indicator.service; colours follow Caelestia's scheme.json.
import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland

ShellRoot {
    id: root

    readonly property int size: 40
    property string state: "idle"
    property int originX: 0
    property int originY: 0
    property bool hasOrigin: false
    property var colours: ({})

    Socket {
        id: sock

        path: `${Quickshell.env("XDG_RUNTIME_DIR")}/mouse-autoscroll/state.sock`
        connected: true
        onConnectionStateChanged: if (!connected) root.state = "idle"

        parser: SplitParser {
            onRead: data => {
                try {
                    const msg = JSON.parse(data);
                    root.state = msg.state ?? "idle";
                    root.hasOrigin = msg.x !== null && msg.y !== null;
                    if (root.hasOrigin) {
                        root.originX = msg.x;
                        root.originY = msg.y;
                    }
                } catch (e) {}
            }
        }
    }

    // The daemon may start later or restart: keep reconnecting.
    Timer {
        interval: 2000
        running: !sock.connected
        repeat: true
        onTriggered: sock.connected = true
    }

    FileView {
        path: `${Quickshell.env("HOME")}/.local/state/caelestia/scheme.json`
        watchChanges: true
        onFileChanged: reload()
        onLoaded: {
            try {
                root.colours = JSON.parse(text()).colours ?? {};
            } catch (e) {}
        }
    }

    function colour(name: string, fallback: string): color {
        return root.colours[name] ? `#${root.colours[name]}` : fallback;
    }

    Variants {
        model: Quickshell.screens

        PanelWindow {
            id: win

            required property ShellScreen modelData
            readonly property int localX: root.originX - modelData.x
            readonly property int localY: root.originY - modelData.y
            readonly property bool onThisScreen: root.hasOrigin
                && localX >= 0 && localX < modelData.width
                && localY >= 0 && localY < modelData.height
            readonly property bool active: root.state !== "idle" && onThisScreen

            screen: modelData
            visible: active
            color: "transparent"

            WlrLayershell.layer: WlrLayer.Overlay
            WlrLayershell.namespace: "mouse-autoscroll-indicator"
            WlrLayershell.keyboardFocus: WlrKeyboardFocus.None
            exclusionMode: ExclusionMode.Ignore
            mask: Region {}

            anchors.top: true
            anchors.left: true
            margins.left: Math.max(0, win.localX - root.size / 2)
            margins.top: Math.max(0, win.localY - root.size / 2)
            implicitWidth: root.size
            implicitHeight: root.size

            Rectangle {
                anchors.fill: parent
                radius: width / 2
                color: Qt.alpha(root.colour("surface", "#010303"), 0.85)
                border.width: root.state === "latched" ? 2 : 1
                border.color: root.state === "latched"
                    ? root.colour("primary", "#80d4da")
                    : Qt.alpha(root.colour("outlineVariant", "#3f4a4b"), 0.6)

                Text {
                    anchors.centerIn: parent
                    text: "open_with"
                    color: root.colour("onSurface", "#dde4e4")
                    font.family: "Material Symbols Rounded"
                    font.pixelSize: 22
                }
            }
        }
    }
}
