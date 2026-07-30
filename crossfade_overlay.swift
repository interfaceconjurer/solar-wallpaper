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
// The duration arg also accepts the literal "hold": instead of fading out and
// exiting, the overlay stays fully visible on top of the freshly-set
// destination wallpaper so scaling/alignment can be inspected statically.
// Used by test_crossfade.sh. Ctrl-C in the terminal exits.
let durationArg = CommandLine.arguments[3]
let holdMode = durationArg.lowercased() == "hold"
let duration = Double(durationArg) ?? 1.0

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

// Rasterize to a CGImage so the overlay can be driven by a CALayer using
// aspect-FILL gravity (see below). NSImageView has no crop-to-fill scaling
// mode, so we render the layer's contents directly.
var fromImageRect = NSRect(origin: .zero, size: fromImage.size)
guard let fromCGImage = fromImage.cgImage(forProposedRect: &fromImageRect, context: nil, hints: nil) else {
    fputs("Error: could not rasterize from image\n", stderr)
    exit(1)
}

let toURL = URL(fileURLWithPath: toPath)

class OverlayDelegate: NSObject, NSApplicationDelegate {
    var windows: [NSWindow] = []
    var sourceImage: CGImage!
    var destURL: URL!
    var fadeDuration: Double = 1.0
    var hold: Bool = false

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
            // A transient borderless window inherits AppKit's default entrance
            // animation, which briefly scales the otherwise-identical source
            // image before our opacity crossfade begins.
            window.animationBehavior = .none

            // Fill the screen exactly like macOS wallpaper does: aspect-FILL
            // (scale to cover, crop the overflow), NOT aspect-fit. A 16:9 still
            // on a taller display (e.g. 3456x2234) would otherwise be
            // letterboxed with black bars top/bottom, so the overlay would not
            // line up with the full-bleed wallpaper underneath it. NSImageView
            // has no crop-to-fill mode, so drive a CALayer directly.
            let contentView = NSView(frame: NSRect(origin: .zero, size: screen.frame.size))
            contentView.wantsLayer = true
            let layer = contentView.layer!
            layer.contents = sourceImage
            layer.contentsGravity = .resizeAspectFill
            layer.contentsScale = screen.backingScaleFactor
            layer.masksToBounds = true
            layer.backgroundColor = NSColor.black.cgColor
            window.contentView = contentView

            window.orderFrontRegardless()
            windows.append(window)
        }

        // Force the overlay windows to draw immediately, then only touch the
        // REAL wallpaper once the window server has actually presented the
        // overlay frame on screen. A fixed delay races on busy systems and
        // external displays: the destination wallpaper gets written before the
        // overlay is composited, briefly exposing it (visible morning→day jump),
        // then the overlay pops on top (day→morning jump) before the fade.
        for window in windows {
            window.displayIfNeeded()
        }

        var didProceed = false
        let proceed = { [weak self] in
            guard let self = self, !didProceed else { return }
            didProceed = true
            self.setDestinationWallpaper()
            if self.hold {
                // Freeze: keep the overlay fully opaque over the destination
                // wallpaper so any aspect-ratio mismatch is static and
                // inspectable. Terminal Ctrl-C exits.
                fputs("Holding overlay for inspection. Press Ctrl-C to exit.\n", stderr)
                return
            }
            self.startFade()
        }

        // Primary path: the CATransaction completion block fires after the
        // overlay layers are committed and presented by the render server. One
        // extra runloop hop guarantees the frame is on screen before we swap the
        // wallpaper underneath it.
        CATransaction.begin()
        CATransaction.setCompletionBlock {
            DispatchQueue.main.async(execute: proceed)
        }
        for window in windows {
            window.contentView?.layer?.setNeedsDisplay()
            window.displayIfNeeded()
        }
        CATransaction.commit()

        // Safety fallback: if no completion fires (e.g. nothing to commit),
        // proceed anyway so a transition never stalls.
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.5, execute: proceed)
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
delegate.sourceImage = fromCGImage
delegate.destURL = toURL
delegate.fadeDuration = duration
delegate.hold = holdMode
app.delegate = delegate
app.run()
