import Cocoa
import QuartzCore

class CrossfadeOverlay: NSObject, NSApplicationDelegate {
    var window: NSWindow!
    var toLayer: CALayer!

    let fromPath: String
    let toPath: String
    let duration: Double
    let midAction: String?

    init(fromPath: String, toPath: String, duration: Double, midAction: String?) {
        self.fromPath = fromPath
        self.toPath = toPath
        self.duration = duration
        self.midAction = midAction
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        guard let screen = NSScreen.main else {
            NSApp.terminate(nil)
            return
        }

        guard let fromImage = NSImage(contentsOfFile: fromPath),
              let toImage = NSImage(contentsOfFile: toPath) else {
            fputs("Error: Could not load images\n", stderr)
            NSApp.terminate(nil)
            return
        }

        let frame = screen.frame

        window = NSWindow(
            contentRect: frame,
            styleMask: .borderless,
            backing: .buffered,
            defer: false
        )
        window.level = NSWindow.Level(rawValue: Int(CGWindowLevelForKey(.desktopWindow)) + 1)
        window.isOpaque = true
        window.backgroundColor = .black
        window.ignoresMouseEvents = true
        window.collectionBehavior = [.canJoinAllSpaces, .stationary]

        let contentView = NSView(frame: frame)
        contentView.wantsLayer = true
        window.contentView = contentView

        let fromLayer = CALayer()
        fromLayer.frame = contentView.bounds
        fromLayer.contents = fromImage.cgImage(forProposedRect: nil, context: nil, hints: nil)
        fromLayer.contentsGravity = .resizeAspectFill
        contentView.layer!.addSublayer(fromLayer)

        toLayer = CALayer()
        toLayer.frame = contentView.bounds
        toLayer.contents = toImage.cgImage(forProposedRect: nil, context: nil, hints: nil)
        toLayer.contentsGravity = .resizeAspectFill
        toLayer.opacity = 0.0
        contentView.layer!.addSublayer(toLayer)

        window.orderFront(nil)

        DispatchQueue.main.asyncAfter(deadline: .now() + 0.1) {
            self.startCrossfade()
        }
    }

    func startCrossfade() {
        let anim = CABasicAnimation(keyPath: "opacity")
        anim.fromValue = 0.0
        anim.toValue = 1.0
        anim.duration = duration
        anim.timingFunction = CAMediaTimingFunction(name: .linear)
        anim.fillMode = .forwards
        anim.isRemovedOnCompletion = false

        CATransaction.begin()
        CATransaction.setCompletionBlock {
            NSAnimationContext.runAnimationGroup({ context in
                context.duration = 1.0
                self.window.animator().alphaValue = 0.0
            }, completionHandler: {
                NSApp.terminate(nil)
            })
        }
        toLayer.add(anim, forKey: "crossfade")
        CATransaction.commit()

        if let action = midAction {
            DispatchQueue.main.asyncAfter(deadline: .now() + duration / 2.0) {
                DispatchQueue.global().async {
                    let process = Process()
                    process.executableURL = URL(fileURLWithPath: "/bin/sh")
                    process.arguments = ["-c", action]
                    try? process.run()
                    process.waitUntilExit()
                }
            }
        }
    }
}

let args = CommandLine.arguments
guard args.count >= 4 else {
    fputs("Usage: crossfade_overlay <from_image> <to_image> <duration_secs> [mid_command]\n", stderr)
    exit(1)
}

let fromPath = args[1]
let toPath = args[2]
let duration = Double(args[3]) ?? 3.0
let midAction = args.count > 4 ? args[4] : nil

let app = NSApplication.shared
let delegate = CrossfadeOverlay(fromPath: fromPath, toPath: toPath, duration: duration, midAction: midAction)
app.delegate = delegate
app.setActivationPolicy(.accessory)
app.run()
