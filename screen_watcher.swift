import Cocoa

class ScreenWatcher: NSObject {
    let scriptDir: String
    let framesDir: String
    let statePath: String
    var lastScreenCount: Int

    override init() {
        let bundle = Bundle.main.executableURL!.deletingLastPathComponent().path
        self.scriptDir = bundle
        self.framesDir = bundle + "/frames"
        self.statePath = bundle + "/.last_period"
        self.lastScreenCount = NSScreen.screens.count
        super.init()

        NotificationCenter.default.addObserver(
            self,
            selector: #selector(screensChanged),
            name: NSApplication.didChangeScreenParametersNotification,
            object: nil
        )
    }

    @objc func screensChanged() {
        let currentCount = NSScreen.screens.count
        guard currentCount > lastScreenCount else {
            lastScreenCount = currentCount
            return
        }
        lastScreenCount = currentCount

        guard let period = currentPeriod() else { return }
        let framePath = framesDir + "/\(period).png"
        guard FileManager.default.fileExists(atPath: framePath) else { return }

        let url = URL(fileURLWithPath: framePath)
        let workspace = NSWorkspace.shared
        for screen in NSScreen.screens {
            do {
                try workspace.setDesktopImageURL(url, for: screen, options: [:])
            } catch {
                fputs("screen_watcher: setDesktopImageURL failed: \(error)\n", stderr)
            }
        }
        fputs("screen_watcher: applied \(period) wallpaper to \(currentCount) screens\n", stderr)
    }

    func currentPeriod() -> String? {
        guard let data = try? String(contentsOfFile: statePath, encoding: .utf8) else {
            return nil
        }
        let period = data.trimmingCharacters(in: .whitespacesAndNewlines)
        return ["morning", "day", "evening", "night"].contains(period) ? period : nil
    }
}

let app = NSApplication.shared
app.setActivationPolicy(.accessory)
let watcher = ScreenWatcher()
_ = watcher // prevent dealloc
app.run()
