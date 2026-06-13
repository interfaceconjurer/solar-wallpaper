import Cocoa
import QuartzCore

// Fullscreen crossfade overlay for seamless wallpaper transitions.
// Usage: crossfade_overlay <from_image> <to_image> <duration_seconds>
//
// Self-contained strategy (no caller ordering required):
// 1. Cover every display with a fullscreen window showing <from_image>.
//    This sits just above the desktop icons but below normal windows, so it
//    visually matches the current wallpaper and covers no app windows.
// 2. Once the window is confirmed on-screen, set the REAL wallpaper to
//    <to_image> via NSWorkspace.setDesktopImageURL on every screen. This
//    write is hidden underneath the overlay, so there is no visible jump.
// 3. Fade the overlay window opacity 1 -> 0 over <duration> at 60fps,
//    dissolving from <from_image> into the now-current <to_image>.
// 4. Exit. macOS owns persistent wallpaper state from here on.

guard CommandLine.arguments.count >= 4 else {
    fputs("Usage: crossfade_overlay <from_image> <to_image> <duration_seconds>\n", stderr)
    exit(1)
}

let fromPath = CommandLine.arguments[1]
let toPath = CommandLine.arguments[2]
let duration = Double(CommandLine.arguments[3]) ?? 1.0

guard FileManager.default.fileExists(atPath: fromPath) else {
    fputs("Error: from image not found: \(fromPath)\n", stderr)
    exit(1)
}
guard FileManager.default.fileExists(atPath: toPath) else {
    fputs("Error: to image not found: \(toPath)\n", stderr)
    exit(1)
}
guard let fromImage = NSImage(contentsOfFile: fromPath) else {
    fputs("Error: could not load from image\n", stderr)
    exit(1)
}

let toURL = URL(fileURLWithPath: toPath)

class OverlayDelegate: NSObject, NSApplicationDelegate {
    var windows: [NSWindow] = []
    var sourceImage: NSImage!
    var destURL: URL!
    var fadeDuration: Double = 1.0

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)

        for screen in NSScreen.screens {
            let window = NSWindow(
                contentRect: screen.frame,
                styleMask: .borderless,
                backing: .buffered,
                defer: false
            )
            // Sit just above desktop icons, below normal windows
            window.level = NSWindow.Level(Int(CGWindowLevelForKey(.desktopIconWindow)) + 1)
            window.isOpaque = true
            window.backgroundColor = .black
            window.collectionBehavior = [.canJoinAllSpaces, .stationary, .ignoresCycle]
            window.ignoresMouseEvents = true
            window.hasShadow = false

            // Image view that fills the screen exactly like macOS wallpaper does
            let imageView = NSImageView(frame: NSRect(origin: .zero, size: screen.frame.size))
            imageView.image = sourceImage
            imageView.imageScaling = .scaleProportionallyUpOrDown
            imageView.imageAlignment = .alignCenter
            window.contentView = imageView

            window.orderFrontRegardless()
            windows.append(window)
        }

        // Wait for the windows to actually render before touching the wallpaper
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.08) {
            self.setDestinationWallpaper()
            self.startFade()
        }
    }

    func setDestinationWallpaper() {
        let ws = NSWorkspace.shared
        let options = ws.desktopImageOptions(for: NSScreen.main ?? NSScreen.screens.first!) ?? [:]
        for screen in NSScreen.screens {
            do {
                try ws.setDesktopImageURL(destURL, for: screen, options: options)
            } catch {
                fputs("Warning: could not set wallpaper on a screen: \(error)\n", stderr)
            }
        }
    }

    func startFade() {
        let group = DispatchGroup()
        for window in windows {
            group.enter()
            NSAnimationContext.runAnimationGroup({ context in
                context.duration = self.fadeDuration
                context.timingFunction = CAMediaTimingFunction(name: .easeInEaseOut)
                window.animator().alphaValue = 0.0
            }, completionHandler: {
                group.leave()
            })
        }
        group.notify(queue: .main) {
            NSApp.terminate(nil)
        }
    }
}

let app = NSApplication.shared
let delegate = OverlayDelegate()
delegate.sourceImage = fromImage
delegate.destURL = toURL
delegate.fadeDuration = duration
app.delegate = delegate
app.run()
