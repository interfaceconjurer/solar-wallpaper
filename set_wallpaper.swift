import Cocoa

// Minimal binary: sets the desktop wallpaper on all screens via NSWorkspace.
// Usage: set_wallpaper <image_path>

guard CommandLine.arguments.count >= 2 else {
    fputs("Usage: set_wallpaper <image_path>\n", stderr)
    exit(1)
}

let path = CommandLine.arguments[1]
let url = URL(fileURLWithPath: path)

guard FileManager.default.fileExists(atPath: path) else {
    fputs("Error: file not found: \(path)\n", stderr)
    exit(1)
}

let workspace = NSWorkspace.shared
var failed = false

for screen in NSScreen.screens {
    do {
        try workspace.setDesktopImageURL(url, for: screen, options: [:])
    } catch {
        fputs("Error setting wallpaper for screen: \(error)\n", stderr)
        failed = true
    }
}

exit(failed ? 1 : 0)
