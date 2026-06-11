import Cocoa

/// Screen watcher daemon:
/// - On wake/unlock: triggers the main solar_wallpaper.py script which handles
///   transitions (stepping from the persisted wallpaper to the current period).
/// - On display connect: applies the current wallpaper to all screens immediately
///   (new displays need the correct image right away, no transition needed).

class ScreenWatcher: NSObject {
    let scriptDir: String
    let framesDir: String
    let statePath: String
    let scriptPath: String
    let setWallpaperBin: String
    var lastScreenCount: Int
    var lastWakeTrigger: Date = .distantPast

    override init() {
        let bundle = Bundle.main.executableURL!.deletingLastPathComponent().path
        self.scriptDir = bundle
        self.framesDir = bundle + "/frames"
        self.statePath = bundle + "/.last_period"
        self.scriptPath = bundle + "/solar_wallpaper.py"
        self.setWallpaperBin = bundle + "/set_wallpaper"
        self.lastScreenCount = NSScreen.screens.count
        super.init()

        NSWorkspace.shared.notificationCenter.addObserver(
            self,
            selector: #selector(didWake),
            name: NSWorkspace.didWakeNotification,
            object: nil
        )

        DistributedNotificationCenter.default().addObserver(
            self,
            selector: #selector(didWake),
            name: NSNotification.Name("com.apple.screenIsUnlocked"),
            object: nil
        )

        NotificationCenter.default.addObserver(
            self,
            selector: #selector(screensChanged),
            name: NSApplication.didChangeScreenParametersNotification,
            object: nil
        )
    }

    @objc func didWake() {
        // Debounce: wake and unlock often fire within seconds of each other
        let now = Date()
        guard now.timeIntervalSince(lastWakeTrigger) > 3.0 else { return }
        lastWakeTrigger = now

        // Give the display a moment to initialize, then trigger the script.
        // The script handles everything: determines the target period,
        // shows the previous wallpaper (already persisted by macOS), and
        // starts the transition to the current period.
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.0) { [self] in
            triggerScript()
        }
    }

    @objc func screensChanged() {
        let currentCount = NSScreen.screens.count
        guard currentCount > lastScreenCount else {
            lastScreenCount = currentCount
            return
        }
        lastScreenCount = currentCount

        // New display connected — apply current wallpaper to all screens immediately
        applyCurrentWallpaper()
    }

    func triggerScript() {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/python3")
        process.arguments = [scriptPath]
        process.currentDirectoryURL = URL(fileURLWithPath: scriptDir)
        // Detach so we don't block the run loop
        do {
            try process.run()
        } catch {
            fputs("screen_watcher: failed to launch script: \(error)\n", stderr)
        }
    }

    func applyCurrentWallpaper() {
        guard let period = currentPeriod() else { return }
        let framePath = framesDir + "/\(period).png"
        guard FileManager.default.fileExists(atPath: framePath) else { return }

        let process = Process()
        process.executableURL = URL(fileURLWithPath: setWallpaperBin)
        process.arguments = [framePath]
        do {
            try process.run()
            process.waitUntilExit()
            fputs("screen_watcher: applied \(period) to \(NSScreen.screens.count) screen(s)\n", stderr)
        } catch {
            fputs("screen_watcher: set_wallpaper failed: \(error)\n", stderr)
        }
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
