import Cocoa
import QuartzCore
import IOKit.pwr_mgt

private let kIOMessageSystemWillSleep: UInt32 = 0xE000_0280
private let kIOMessageSystemWillPowerOn: UInt32 = 0xE000_0320
private let kIOMessageSystemHasPoweredOn: UInt32 = 0xE000_0300

class SolarDaemon: NSObject, NSApplicationDelegate {
    let scriptDir: String
    let framesDir: String
    let statePath: String
    let pidPath: String

    var windows: [NSWindow] = []
    var currentLayers: [CALayer] = []
    var currentPeriod: String = ""
    var isCrossfading: Bool = false

    let periods = ["morning", "day", "evening", "night"]
    let transitionTimes: [(hour: Int, minute: Int, period: String)] = [
        (12, 0, "day"),
        (19, 0, "evening"),
        (23, 0, "night"),
    ]

    var rootPort: io_connect_t = 0
    var notifyPortRef: IONotificationPortRef?
    var notifierObject: io_object_t = 0

    override init() {
        let execURL = URL(fileURLWithPath: CommandLine.arguments[0])
        self.scriptDir = execURL.deletingLastPathComponent().path
        self.framesDir = scriptDir + "/frames"
        self.statePath = scriptDir + "/.last_period"
        self.pidPath = scriptDir + "/.daemon_pid"
        super.init()
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        writePidFile()
        setupSignalHandler()
        loadCurrentPeriod()
        createOverlayWindows()
        registerPowerNotifications()
        registerWakeNotifications()
        registerDisplayNotifications()
        registerScreenUnlockNotification()
    }

    func applicationWillTerminate(_ notification: Notification) {
        try? FileManager.default.removeItem(atPath: pidPath)
    }

    // MARK: - PID File

    func writePidFile() {
        let pid = ProcessInfo.processInfo.processIdentifier
        try? "\(pid)".write(toFile: pidPath, atomically: true, encoding: .utf8)
    }

    // MARK: - Signal Handling (SIGUSR1 from scheduler)

    func setupSignalHandler() {
        let source = DispatchSource.makeSignalSource(signal: SIGUSR1, queue: .main)
        source.setEventHandler { [weak self] in
            self?.handleScheduledTransition()
        }
        source.resume()
        signal(SIGUSR1, SIG_IGN)
    }

    func handleScheduledTransition() {
        let newPeriod = determineCurrentPeriod()
        if newPeriod != currentPeriod {
            crossfade(to: newPeriod, duration: 1800.0)
        }
    }

    // MARK: - Period Determination

    func determineCurrentPeriod() -> String {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/python3")
        process.arguments = ["-c", """
            import sys; sys.path.insert(0, '\(scriptDir)')
            from solar_wallpaper import get_location, get_period
            lat, lon = get_location()
            print(get_period(lat, lon))
            """]
        let pipe = Pipe()
        process.standardOutput = pipe
        process.standardError = FileHandle.nullDevice
        try? process.run()
        process.waitUntilExit()
        let data = pipe.fileHandleForReading.readDataToEndOfFile()
        let result = String(data: data, encoding: .utf8)?.trimmingCharacters(in: .whitespacesAndNewlines)
        return result ?? currentPeriod
    }

    func loadCurrentPeriod() {
        if let saved = try? String(contentsOfFile: statePath, encoding: .utf8).trimmingCharacters(in: .whitespacesAndNewlines),
           periods.contains(saved) {
            currentPeriod = saved
        } else {
            currentPeriod = determineCurrentPeriod()
            saveState()
        }
    }

    func saveState() {
        try? currentPeriod.write(toFile: statePath, atomically: true, encoding: .utf8)
    }

    // MARK: - Overlay Windows

    func createOverlayWindows() {
        guard let image = loadFrame(currentPeriod) else {
            fputs("Error: Could not load frame for \(currentPeriod)\n", stderr)
            return
        }

        for screen in NSScreen.screens {
            let window = createWindow(for: screen, image: image)
            windows.append(window)
        }
    }

    func createWindow(for screen: NSScreen, image: NSImage) -> NSWindow {
        let frame = screen.frame

        let window = NSWindow(
            contentRect: frame,
            styleMask: .borderless,
            backing: .buffered,
            defer: false
        )
        window.level = NSWindow.Level(rawValue: Int(CGWindowLevelForKey(.desktopIconWindow)) + 1)
        window.isOpaque = true
        window.backgroundColor = .black
        window.ignoresMouseEvents = true
        window.collectionBehavior = [.canJoinAllSpaces, .stationary]

        let contentView = NSView(frame: NSRect(origin: .zero, size: frame.size))
        contentView.wantsLayer = true
        window.contentView = contentView

        let layer = CALayer()
        layer.frame = contentView.bounds
        layer.contents = image.cgImage(forProposedRect: nil, context: nil, hints: nil)
        layer.contentsGravity = .resizeAspectFill
        contentView.layer!.addSublayer(layer)

        window.orderFront(nil)
        currentLayers.append(layer)

        return window
    }

    func loadFrame(_ period: String) -> NSImage? {
        let path = framesDir + "/\(period).png"
        return NSImage(contentsOfFile: path)
    }

    // MARK: - Crossfade

    func crossfade(to newPeriod: String, duration: Double) {
        guard !isCrossfading else { return }
        guard let newImage = loadFrame(newPeriod) else {
            fputs("Error: Could not load frame for \(newPeriod)\n", stderr)
            return
        }
        isCrossfading = true

        fputs("Crossfading \(currentPeriod) → \(newPeriod) (\(Int(duration))s)\n", stderr)

        var newLayers: [CALayer] = []

        for window in windows {
            guard let contentView = window.contentView else { continue }

            let toLayer = CALayer()
            toLayer.frame = contentView.bounds
            toLayer.contents = newImage.cgImage(forProposedRect: nil, context: nil, hints: nil)
            toLayer.contentsGravity = .resizeAspectFill
            toLayer.opacity = 0.0
            contentView.layer!.addSublayer(toLayer)

            let anim = CABasicAnimation(keyPath: "opacity")
            anim.fromValue = 0.0
            anim.toValue = 1.0
            anim.duration = duration
            anim.timingFunction = CAMediaTimingFunction(name: .easeInEaseOut)
            anim.fillMode = .forwards
            anim.isRemovedOnCompletion = false
            toLayer.add(anim, forKey: "crossfade")

            newLayers.append(toLayer)
        }

        DispatchQueue.main.asyncAfter(deadline: .now() + duration + 0.5) { [weak self] in
            guard let self = self else { return }

            // Remove old layers
            for layer in self.currentLayers {
                layer.removeFromSuperlayer()
            }
            // Promote new layers, reset opacity to 1.0 without animation
            for layer in newLayers {
                layer.removeAllAnimations()
                layer.opacity = 1.0
            }
            self.currentLayers = newLayers
            self.currentPeriod = newPeriod
            self.isCrossfading = false
            self.saveState()
            self.switchUnderlyingWallpaper(newPeriod)
        }
    }

    // MARK: - Wallpaper Switch (underneath overlay)

    func switchUnderlyingWallpaper(_ period: String) {
        let framePath = framesDir + "/\(period).png"
        let script = """
            tell application "System Events"
                tell every desktop
                    set picture to "\(framePath)"
                end tell
            end tell
            """
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/osascript")
        process.arguments = ["-e", script]
        process.standardOutput = FileHandle.nullDevice
        process.standardError = FileHandle.nullDevice
        try? process.run()
    }

    // MARK: - Wake/Power Notifications

    func registerPowerNotifications() {
        rootPort = IORegisterForSystemPower(
            Unmanaged.passUnretained(self).toOpaque(),
            &notifyPortRef,
            powerCallback,
            &notifierObject
        )
        if rootPort != 0, let port = notifyPortRef {
            CFRunLoopAddSource(
                CFRunLoopGetMain(),
                IONotificationPortGetRunLoopSource(port).takeUnretainedValue(),
                .defaultMode
            )
        }
    }

    func registerWakeNotifications() {
        NSWorkspace.shared.notificationCenter.addObserver(
            self,
            selector: #selector(handleWake),
            name: NSWorkspace.didWakeNotification,
            object: nil
        )
        NSWorkspace.shared.notificationCenter.addObserver(
            self,
            selector: #selector(handleWake),
            name: NSWorkspace.screensDidWakeNotification,
            object: nil
        )
    }

    func registerScreenUnlockNotification() {
        DistributedNotificationCenter.default().addObserver(
            self,
            selector: #selector(handleWake),
            name: NSNotification.Name("com.apple.screenIsUnlocked"),
            object: nil
        )
    }

    func registerDisplayNotifications() {
        NotificationCenter.default.addObserver(
            self,
            selector: #selector(displayConfigChanged),
            name: NSApplication.didChangeScreenParametersNotification,
            object: nil
        )
    }

    @objc func handleWake(_ notification: Notification? = nil) {
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { [weak self] in
            guard let self = self else { return }
            let newPeriod = self.determineCurrentPeriod()
            if newPeriod != self.currentPeriod {
                self.crossfade(to: newPeriod, duration: 30.0)
            }
        }
    }

    @objc func displayConfigChanged() {
        rebuildWindows()
    }

    func rebuildWindows() {
        for window in windows {
            window.orderOut(nil)
        }
        windows.removeAll()
        currentLayers.removeAll()

        guard let image = loadFrame(currentPeriod) else { return }
        for screen in NSScreen.screens {
            let window = createWindow(for: screen, image: image)
            windows.append(window)
        }
    }
}

// MARK: - IOKit Power Callback (C function)

func powerCallback(
    _ refcon: UnsafeMutableRawPointer?,
    _ service: io_service_t,
    _ messageType: UInt32,
    _ messageArgument: UnsafeMutableRawPointer?
) {
    guard let refcon = refcon else { return }
    let daemon = Unmanaged<SolarDaemon>.fromOpaque(refcon).takeUnretainedValue()

    switch messageType {
    case kIOMessageSystemWillPowerOn:
        DispatchQueue.main.async {
            daemon.handleWake()
        }
    case kIOMessageSystemHasPoweredOn:
        break
    case kIOMessageSystemWillSleep:
        let arg = Int(Int32(bitPattern: UInt32(truncatingIfNeeded: Int(bitPattern: messageArgument))))
        IOAllowPowerChange(daemon.rootPort, arg)
    default:
        break
    }
}

// MARK: - Entry Point

let app = NSApplication.shared
let daemon = SolarDaemon()
app.delegate = daemon
app.setActivationPolicy(.accessory)
app.run()
