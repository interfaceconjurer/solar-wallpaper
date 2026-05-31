import Cocoa

class WakeWatcher {
    let scriptPath: String

    init(scriptPath: String) {
        self.scriptPath = scriptPath

        NSWorkspace.shared.notificationCenter.addObserver(
            self,
            selector: #selector(didWake),
            name: NSWorkspace.didWakeNotification,
            object: nil
        )

        NSWorkspace.shared.notificationCenter.addObserver(
            self,
            selector: #selector(didWake),
            name: NSWorkspace.screensDidWakeNotification,
            object: nil
        )
    }

    @objc func didWake(_ notification: Notification) {
        DispatchQueue.global().asyncAfter(deadline: .now() + 2.0) {
            let process = Process()
            process.executableURL = URL(fileURLWithPath: "/usr/bin/python3")
            process.arguments = [self.scriptPath]
            try? process.run()
            process.waitUntilExit()
        }
    }
}

let scriptDir = URL(fileURLWithPath: CommandLine.arguments[0])
    .deletingLastPathComponent().path
let scriptPath = scriptDir + "/solar_wallpaper.py"

let watcher = WakeWatcher(scriptPath: scriptPath)
let app = NSApplication.shared
app.setActivationPolicy(.accessory)
app.run()
