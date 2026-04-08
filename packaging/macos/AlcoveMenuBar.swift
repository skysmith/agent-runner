import AppKit
import Foundation

final class FolderDropView: NSView {
    weak var button: NSStatusBarButton?
    var onFolderDropped: ((String) -> Void)?
    private var isDropTarget = false {
        didSet {
            needsDisplay = true
        }
    }

    override init(frame frameRect: NSRect) {
        super.init(frame: frameRect)
        registerForDraggedTypes([.fileURL])
        wantsLayer = true
    }

    required init?(coder: NSCoder) {
        super.init(coder: coder)
        registerForDraggedTypes([.fileURL])
        wantsLayer = true
    }

    override func mouseDown(with event: NSEvent) {
        button?.performClick(nil)
    }

    override func draggingEntered(_ sender: NSDraggingInfo) -> NSDragOperation {
        guard folderPath(from: sender.draggingPasteboard) != nil else {
            isDropTarget = false
            return []
        }
        isDropTarget = true
        return .copy
    }

    override func draggingExited(_ sender: NSDraggingInfo?) {
        isDropTarget = false
    }

    override func draggingEnded(_ sender: NSDraggingInfo) {
        isDropTarget = false
    }

    override func prepareForDragOperation(_ sender: NSDraggingInfo) -> Bool {
        folderPath(from: sender.draggingPasteboard) != nil
    }

    override func performDragOperation(_ sender: NSDraggingInfo) -> Bool {
        defer {
            isDropTarget = false
        }
        guard let folderPath = folderPath(from: sender.draggingPasteboard) else {
            return false
        }
        onFolderDropped?(folderPath)
        return true
    }

    override func concludeDragOperation(_ sender: NSDraggingInfo?) {
        isDropTarget = false
    }

    override func draw(_ dirtyRect: NSRect) {
        super.draw(dirtyRect)
        guard isDropTarget else { return }
        NSColor.controlAccentColor.withAlphaComponent(0.18).setFill()
        NSBezierPath(roundedRect: bounds.insetBy(dx: 2, dy: 2), xRadius: 6, yRadius: 6).fill()
    }

    private func folderPath(from pasteboard: NSPasteboard) -> String? {
        let options: [NSPasteboard.ReadingOptionKey: Any] = [
            .urlReadingFileURLsOnly: true,
        ]
        guard
            let urls = pasteboard.readObjects(forClasses: [NSURL.self], options: options) as? [URL]
        else {
            return nil
        }
        for url in urls {
            if let values = try? url.resourceValues(forKeys: [.isDirectoryKey]), values.isDirectory == true {
                return url.path
            }
            var isDirectory = ObjCBool(false)
            if FileManager.default.fileExists(atPath: url.path, isDirectory: &isDirectory), isDirectory.boolValue {
                return url.path
            }
        }
        return nil
    }
}

final class MenuBarController: NSObject, NSApplicationDelegate {
    private let statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
    private let statePath = FileManager.default.homeDirectoryForCurrentUser
        .appendingPathComponent("Library/Application Support/agent-runner/wrapper-runtime.json")
    private var timer: Timer?
    private let statusLineView = NSTextField(labelWithString: "Loading Alcove...")
    private let statusLineContainer = NSView(frame: NSRect(x: 0, y: 0, width: 290, height: 24))

    private let statusLine = NSMenuItem(title: "Loading Alcove…", action: nil, keyEquivalent: "")
    private let openItem = NSMenuItem(title: "Open Alcove", action: #selector(openAlcove), keyEquivalent: "")
    private let openWorkspaceItem = NSMenuItem(title: "Open Workspace Folder", action: #selector(openCurrentWorkspace), keyEquivalent: "")
    private let stopItem = NSMenuItem(title: "Stop Run", action: #selector(stopRun), keyEquivalent: "")
    private let copyLocalItem = NSMenuItem(title: "Copy Local URL", action: #selector(copyLocalURL), keyEquivalent: "")
    private let copyPhoneItem = NSMenuItem(title: "Copy Phone URL", action: #selector(copyPhoneURL), keyEquivalent: "")
    private let restartItem = NSMenuItem(title: "Restart Service", action: #selector(restartService), keyEquivalent: "")
    private let quitItem = NSMenuItem(title: "Quit Menu Bar", action: #selector(quitHelper), keyEquivalent: "")
    private let dropTargetView = FolderDropView(frame: .zero)

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
        configureStatusLineView()
        statusLine.view = statusLineContainer
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
        configureDropTarget()
        updateMenu()
    }

    private func configureStatusLineView() {
        statusLineView.translatesAutoresizingMaskIntoConstraints = false
        statusLineView.lineBreakMode = .byTruncatingTail
        statusLineContainer.addSubview(statusLineView)
        NSLayoutConstraint.activate([
            statusLineView.leadingAnchor.constraint(equalTo: statusLineContainer.leadingAnchor, constant: 10),
            statusLineView.trailingAnchor.constraint(equalTo: statusLineContainer.trailingAnchor, constant: -10),
            statusLineView.centerYAnchor.constraint(equalTo: statusLineContainer.centerYAnchor),
        ])
    }

    private func refreshState() {
        state = WrapperState.load(from: statePath)
        updateMenu()
    }

    private func configureDropTarget() {
        guard let button = statusItem.button, dropTargetView.superview == nil else { return }
        dropTargetView.translatesAutoresizingMaskIntoConstraints = false
        dropTargetView.button = button
        dropTargetView.onFolderDropped = { [weak self] folderPath in
            self?.openDroppedFolder(folderPath)
        }
        button.addSubview(dropTargetView)
        NSLayoutConstraint.activate([
            dropTargetView.leadingAnchor.constraint(equalTo: button.leadingAnchor),
            dropTargetView.trailingAnchor.constraint(equalTo: button.trailingAnchor),
            dropTargetView.topAnchor.constraint(equalTo: button.topAnchor),
            dropTargetView.bottomAnchor.constraint(equalTo: button.bottomAnchor),
        ])
    }

    private func updateMenu() {
        let button = statusItem.button
        button?.title = ""
        button?.attributedTitle = NSAttributedString(
            string: state.compactTitle,
            attributes: [
                .foregroundColor: NSColor.labelColor,
                .font: NSFont.systemFont(ofSize: 12, weight: .semibold),
            ]
        )
        button?.toolTip = state.tooltip

        statusLineView.attributedStringValue = state.statusLineAttributedTitle
        openItem.isEnabled = state.binaryPath != nil || state.localURL != nil
        openWorkspaceItem.isEnabled = state.binaryPath != nil && state.hasWorkspaceFolderTarget
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

    private func openDroppedFolder(_ folderPath: String) {
        guard !folderPath.isEmpty else { return }
        _ = launchFolderImport(folderPath)
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

    @discardableResult
    private func launchFolderImport(_ folderPath: String) -> Bool {
        guard let binaryPath = state.binaryPath else { return false }
        let process = Process()
        process.executableURL = URL(fileURLWithPath: binaryPath)
        process.arguments = ["--open-folder", folderPath]
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
    let repoPath: String?
    let workspaceName: String?
    let preferredWorkspaceID: String?
    let activeWorkspaceID: String?
    let runState: String
    let runStep: String

    static let empty = WrapperState(
        binaryPath: nil,
        localURL: nil,
        phoneURL: nil,
        repoPath: nil,
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
            repoPath: raw["repo_path"] as? String,
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

    var hasWorkspaceFolderTarget: Bool {
        activeWorkspaceID != nil || preferredWorkspaceID != nil || repoPath != nil
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

    var compactAttributedTitle: NSAttributedString {
        statusAttributedString(
            label: compactTitle,
            font: NSFont.systemFont(ofSize: 12, weight: .semibold),
            textColor: .labelColor
        )
    }

    var tooltip: String {
        if let workspace = workspaceLabel {
            return "\(workspace)\n\(runState.capitalized): \(runStep)"
        }
        return fallbackStatusText
    }

    var statusLine: String {
        if let workspace = workspaceLabel {
            return "\(workspace) — \(runState.capitalized): \(runStep)"
        }
        return fallbackStatusText
    }

    var statusLineAttributedTitle: NSAttributedString {
        statusAttributedString(
            label: statusLine,
            font: NSFont.systemFont(ofSize: 12, weight: .medium),
            textColor: .labelColor
        )
    }

    private var statusColor: NSColor {
        switch runState {
        case "running", "starting", "stopping":
            return .systemOrange
        case "failed":
            return .systemRed
        default:
            return .systemGreen
        }
    }

    private var workspaceLabel: String? {
        let candidate = workspaceName ?? activeWorkspaceID ?? preferredWorkspaceID
        guard let text = candidate?.trimmingCharacters(in: .whitespacesAndNewlines), !text.isEmpty else {
            return nil
        }
        return text
    }

    private var fallbackStatusText: String {
        switch runState {
        case "idle", "succeeded":
            return "Idle."
        default:
            return "\(runState.capitalized): \(runStep)"
        }
    }

    private func statusAttributedString(label: String, font: NSFont, textColor: NSColor) -> NSAttributedString {
        let result = NSMutableAttributedString(
            string: "● ",
            attributes: [
                .foregroundColor: statusColor,
                .font: font,
            ]
        )
        result.append(
            NSAttributedString(
                string: label,
                attributes: [
                    .foregroundColor: textColor,
                    .font: font,
                ]
            )
        )
        return result
    }
}

let app = NSApplication.shared
let delegate = MenuBarController()
app.delegate = delegate
app.run()
