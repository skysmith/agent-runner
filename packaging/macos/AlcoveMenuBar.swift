import AppKit
import Foundation

final class MenuBarController: NSObject, NSApplicationDelegate {
    private let statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
    private let statePath = FileManager.default.homeDirectoryForCurrentUser
        .appendingPathComponent("Library/Application Support/agent-runner/wrapper-runtime.json")
    private var timer: Timer?

    private let statusLine = NSMenuItem(title: "Loading Alcove…", action: nil, keyEquivalent: "")
    private let openItem = NSMenuItem(title: "Open Alcove", action: #selector(openAlcove), keyEquivalent: "")
    private let openWorkspaceItem = NSMenuItem(title: "Open Current Workspace", action: #selector(openCurrentWorkspace), keyEquivalent: "")
    private let stopItem = NSMenuItem(title: "Stop Run", action: #selector(stopRun), keyEquivalent: "")
    private let copyLocalItem = NSMenuItem(title: "Copy Local URL", action: #selector(copyLocalURL), keyEquivalent: "")
    private let copyPhoneItem = NSMenuItem(title: "Copy Phone URL", action: #selector(copyPhoneURL), keyEquivalent: "")
    private let restartItem = NSMenuItem(title: "Restart Service", action: #selector(restartService), keyEquivalent: "")
    private let quitItem = NSMenuItem(title: "Quit Menu Bar", action: #selector(quitHelper), keyEquivalent: "")

    private var state = WrapperState.empty

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)
        configureMenu()
        refreshState()
        timer = Timer.scheduledTimer(withTimeInterval: 1.5, repeats: true) { [weak self] _ in
            self?.refreshState()
        }
    }

    func applicationWillTerminate(_ notification: Notification) {
        timer?.invalidate()
    }

    private func configureMenu() {
        let menu = NSMenu()
        statusLine.isEnabled = false
        menu.addItem(statusLine)
        menu.addItem(.separator())
        menu.addItem(openItem)
        menu.addItem(openWorkspaceItem)
        menu.addItem(stopItem)
        menu.addItem(.separator())
        menu.addItem(copyLocalItem)
        menu.addItem(copyPhoneItem)
        menu.addItem(.separator())
        menu.addItem(restartItem)
        menu.addItem(.separator())
        menu.addItem(quitItem)

        for item in [openItem, openWorkspaceItem, stopItem, copyLocalItem, copyPhoneItem, restartItem, quitItem] {
            item.target = self
        }

        statusItem.menu = menu
        updateMenu()
    }

    private func refreshState() {
        state = WrapperState.load(from: statePath)
        updateMenu()
    }

    private func updateMenu() {
        let button = statusItem.button
        let title = state.compactTitle
        button?.title = title
        button?.toolTip = state.tooltip

        statusLine.title = state.statusLine
        openItem.isEnabled = state.binaryPath != nil || state.localURL != nil
        openWorkspaceItem.isEnabled = state.binaryPath != nil || state.preferredWorkspaceID != nil || state.activeWorkspaceID != nil
        stopItem.isEnabled = state.isRunActive && state.binaryPath != nil
        copyLocalItem.isEnabled = state.localURL != nil
        copyPhoneItem.isEnabled = state.phoneURL != nil
        restartItem.isEnabled = state.binaryPath != nil
    }

    @objc private func openAlcove() {
        if !runControlAction("open-browser") {
            openURL(state.localURL)
        }
    }

    @objc private func openCurrentWorkspace() {
        if !runControlAction("open-current-workspace") {
            openURL(state.localURL)
        }
    }

    @objc private func stopRun() {
        _ = runControlAction("stop-run")
    }

    @objc private func copyLocalURL() {
        _ = runControlAction("copy-local-url")
    }

    @objc private func copyPhoneURL() {
        _ = runControlAction("copy-phone-url")
    }

    @objc private func restartService() {
        _ = runControlAction("restart-service")
    }

    @objc private func quitHelper() {
        NSApp.terminate(nil)
    }

    @discardableResult
    private func runControlAction(_ action: String) -> Bool {
        guard let binaryPath = state.binaryPath else { return false }
        let process = Process()
        process.executableURL = URL(fileURLWithPath: binaryPath)
        process.arguments = ["--control", action]
        process.standardOutput = FileHandle.nullDevice
        process.standardError = FileHandle.nullDevice
        do {
            try process.run()
            return true
        } catch {
            return false
        }
    }

    private func openURL(_ urlString: String?) {
        guard let urlString, let url = URL(string: urlString) else { return }
        NSWorkspace.shared.open(url)
    }
}

struct WrapperState {
    let binaryPath: String?
    let localURL: String?
    let phoneURL: String?
    let workspaceName: String?
    let preferredWorkspaceID: String?
    let activeWorkspaceID: String?
    let runState: String
    let runStep: String

    static let empty = WrapperState(
        binaryPath: nil,
        localURL: nil,
        phoneURL: nil,
        workspaceName: nil,
        preferredWorkspaceID: nil,
        activeWorkspaceID: nil,
        runState: "idle",
        runStep: "Idle"
    )

    static func load(from path: URL) -> WrapperState {
        guard
            let data = try? Data(contentsOf: path),
            let raw = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        else {
            return .empty
        }
        let serverInfo = raw["server_info"] as? [String: Any] ?? [:]
        let runStatus = raw["run_status"] as? [String: Any] ?? [:]
        return WrapperState(
            binaryPath: raw["binary_path"] as? String,
            localURL: (serverInfo["local_url"] as? String) ?? (serverInfo["localhost_url"] as? String),
            phoneURL: serverInfo["phone_url"] as? String,
            workspaceName: raw["workspace_name"] as? String,
            preferredWorkspaceID: raw["preferred_workspace_id"] as? String,
            activeWorkspaceID: runStatus["workspace_id"] as? String,
            runState: (runStatus["state"] as? String) ?? "idle",
            runStep: (runStatus["step"] as? String) ?? "Idle"
        )
    }

    var isRunActive: Bool {
        ["starting", "running", "stopping"].contains(runState)
    }

    var compactTitle: String {
        switch runState {
        case "running":
            return "Alcove • Run"
        case "starting":
            return "Alcove • Prep"
        case "stopping":
            return "Alcove • Stop"
        case "failed":
            return "Alcove • Fix"
        case "succeeded":
            return "Alcove • Done"
        default:
            return "Alcove"
        }
    }

    var tooltip: String {
        let workspace = workspaceName ?? activeWorkspaceID ?? preferredWorkspaceID ?? "No workspace selected"
        return "\(workspace)\n\(runState.capitalized): \(runStep)"
    }

    var statusLine: String {
        let workspace = workspaceName ?? activeWorkspaceID ?? preferredWorkspaceID ?? "No workspace selected"
        return "\(workspace) — \(runState.capitalized): \(runStep)"
    }
}

let app = NSApplication.shared
let delegate = MenuBarController()
app.delegate = delegate
app.run()
