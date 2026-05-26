import Cocoa
import QuartzCore

class CycleOverlay: NSObject, NSApplicationDelegate {
    var window: NSWindow!
    var layers: [CALayer] = []

    let imagePaths: [String]
    let fadeDuration: Double

    init(imagePaths: [String], fadeDuration: Double) {
        self.imagePaths = imagePaths
        self.fadeDuration = fadeDuration
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        guard let screen = NSScreen.main else {
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

        // Stack all images as layers with aspect-fill, first visible, rest hidden
        for (i, path) in imagePaths.enumerated() {
            guard let image = NSImage(contentsOfFile: path),
                  let cgImage = image.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
                fputs("Could not load: \(path)\n", stderr)
                NSApp.terminate(nil)
                return
            }

            let layer = CALayer()
            layer.frame = contentView.bounds
            layer.contents = cgImage
            layer.contentsGravity = .resizeAspectFill
            layer.opacity = i == 0 ? 1.0 : 0.0
            contentView.layer!.addSublayer(layer)
            layers.append(layer)
        }

        window.orderFront(nil)

        DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) {
            self.startCycle()
        }
    }

    func startCycle() {
        // Chain animations: fade in each subsequent layer one after another
        let totalTransitions = layers.count - 1

        for i in 0..<totalTransitions {
            let delay = Double(i) * fadeDuration
            DispatchQueue.main.asyncAfter(deadline: .now() + delay) {
                let anim = CABasicAnimation(keyPath: "opacity")
                anim.fromValue = 0.0
                anim.toValue = 1.0
                anim.duration = self.fadeDuration
                anim.timingFunction = CAMediaTimingFunction(name: .linear)
                anim.fillMode = .forwards
                anim.isRemovedOnCompletion = false
                self.layers[i + 1].add(anim, forKey: "fadeIn")
            }
        }

        // After all transitions complete, hold for a moment then exit
        let totalDuration = Double(totalTransitions) * fadeDuration
        DispatchQueue.main.asyncAfter(deadline: .now() + totalDuration + 1.0) {
            NSAnimationContext.runAnimationGroup({ context in
                context.duration = 1.0
                self.window.animator().alphaValue = 0.0
            }, completionHandler: {
                NSApp.terminate(nil)
            })
        }
    }
}

let args = CommandLine.arguments
guard args.count >= 3 else {
    fputs("Usage: crossfade_cycle <fade_secs> <image1> <image2> [image3] ...\n", stderr)
    exit(1)
}

let fadeDuration = Double(args[1]) ?? 5.0
let imagePaths = Array(args[2...])

let app = NSApplication.shared
let delegate = CycleOverlay(imagePaths: imagePaths, fadeDuration: fadeDuration)
app.delegate = delegate
app.setActivationPolicy(.accessory)
app.run()
