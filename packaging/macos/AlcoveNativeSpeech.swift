import AVFoundation
import Foundation
import Speech

struct SpeechOutput: Encodable {
    let transcript: String?
    let detail: String?
    let locale: String
    let provider: String
}

enum SpeechCLIError: LocalizedError {
    case invalidArguments(String)
    case unavailable(String)

    var errorDescription: String? {
        switch self {
        case .invalidArguments(let detail), .unavailable(let detail):
            return detail
        }
    }
}

final class LiveSpeechSession {
    private let recognizer: SFSpeechRecognizer
    private let request = SFSpeechAudioBufferRecognitionRequest()
    private let audioEngine = AVAudioEngine()
    private let startedAt = Date()
    private let silenceWindow: TimeInterval
    private let noSpeechTimeout: TimeInterval
    private let maxDuration: TimeInterval
    private let finalizationWindow: TimeInterval
    private let threshold: Float
    private let stateLock = NSLock()
    private let monitorQueue = DispatchQueue(label: "local.alcove.native-speech.monitor")

    private var recognitionTask: SFSpeechRecognitionTask?
    private var monitorTimer: DispatchSourceTimer?
    private var tapInstalled = false

    private var bestTranscript = ""
    private var heardSpeech = false
    private var lastSpeechAt = Date()
    private var finishRequestedAt: Date?
    private var result: Result<String, Error>?

    init(
        locale: Locale,
        silenceWindow: TimeInterval = 1.1,
        noSpeechTimeout: TimeInterval = 8.0,
        maxDuration: TimeInterval = 30.0,
        finalizationWindow: TimeInterval = 2.0,
        threshold: Float = 0.015
    ) throws {
        guard let recognizer = SFSpeechRecognizer(locale: locale) else {
            throw SpeechCLIError.unavailable("Native speech recognition is not available for \(locale.identifier).")
        }
        self.recognizer = recognizer
        self.silenceWindow = silenceWindow
        self.noSpeechTimeout = noSpeechTimeout
        self.maxDuration = maxDuration
        self.finalizationWindow = finalizationWindow
        self.threshold = threshold
    }

    func transcribe() throws -> String {
        try authorizeIfNeeded()
        guard recognizer.isAvailable else {
            throw SpeechCLIError.unavailable("Speech recognition is not available right now.")
        }

        request.shouldReportPartialResults = true
        request.taskHint = .dictation
        if recognizer.supportsOnDeviceRecognition {
            request.requiresOnDeviceRecognition = true
        }

        let inputNode = audioEngine.inputNode
        let format = inputNode.outputFormat(forBus: 0)
        guard format.sampleRate > 0, format.channelCount > 0 else {
            throw SpeechCLIError.unavailable("Microphone input is not available.")
        }

        inputNode.installTap(onBus: 0, bufferSize: 1024, format: format) { [weak self] buffer, _ in
            guard let self else { return }
            self.request.append(buffer)
            if self.peakLevel(in: buffer) >= self.threshold {
                self.noteSpeechDetected()
            }
        }
        tapInstalled = true

        audioEngine.prepare()
        try audioEngine.start()
        recognitionTask = recognizer.recognitionTask(with: request) { [weak self] result, error in
            self?.handleRecognition(result: result, error: error)
        }
        startMonitor()

        guard let outcome = waitForResult(timeout: maxDuration + finalizationWindow + 5.0) else {
            cleanup()
            throw SpeechCLIError.unavailable("Native transcription timed out.")
        }

        cleanup()
        let transcript = try outcome.get().trimmingCharacters(in: .whitespacesAndNewlines)
        if transcript.isEmpty {
            throw SpeechCLIError.unavailable("No speech was detected.")
        }
        return transcript
    }

    private func authorizeIfNeeded() throws {
        guard requestMicrophoneAccess() else {
            throw SpeechCLIError.unavailable("Microphone access is required for native speech to text.")
        }

        switch requestSpeechAuthorization() {
        case .authorized:
            return
        case .denied:
            throw SpeechCLIError.unavailable("Speech recognition access was denied for Alcove.")
        case .restricted:
            throw SpeechCLIError.unavailable("Speech recognition is restricted on this Mac.")
        case .notDetermined:
            throw SpeechCLIError.unavailable("Speech recognition permission is still pending. Please try again.")
        @unknown default:
            throw SpeechCLIError.unavailable("Speech recognition is unavailable right now.")
        }
    }

    private func requestSpeechAuthorization() -> SFSpeechRecognizerAuthorizationStatus {
        let current = SFSpeechRecognizer.authorizationStatus()
        if current != .notDetermined {
            return current
        }
        var resolved: SFSpeechRecognizerAuthorizationStatus?
        SFSpeechRecognizer.requestAuthorization { status in
            resolved = status
        }
        return waitForValue(timeout: 15.0) { resolved } ?? .notDetermined
    }

    private func requestMicrophoneAccess() -> Bool {
        switch AVCaptureDevice.authorizationStatus(for: .audio) {
        case .authorized:
            return true
        case .notDetermined:
            var granted: Bool?
            AVCaptureDevice.requestAccess(for: .audio) { allowed in
                granted = allowed
            }
            return waitForValue(timeout: 15.0) { granted } ?? false
        case .denied, .restricted:
            return false
        @unknown default:
            return false
        }
    }

    private func startMonitor() {
        let timer = DispatchSource.makeTimerSource(queue: monitorQueue)
        timer.schedule(deadline: .now() + .milliseconds(200), repeating: .milliseconds(200))
        timer.setEventHandler { [weak self] in
            self?.checkProgress()
        }
        monitorTimer = timer
        timer.resume()
    }

    private func checkProgress() {
        if currentResult() != nil {
            return
        }

        let now = Date()
        if let finishRequestedAt = finishRequestedTime() {
            if now.timeIntervalSince(finishRequestedAt) >= finalizationWindow {
                let best = currentBestTranscript()
                if best.isEmpty {
                    complete(.failure(SpeechCLIError.unavailable("Could not capture speech. Please try again.")))
                } else {
                    complete(.success(best))
                }
            }
            return
        }

        if !hasHeardSpeech(), now.timeIntervalSince(startedAt) >= noSpeechTimeout {
            complete(.failure(SpeechCLIError.unavailable("No speech was detected.")))
            return
        }

        if hasHeardSpeech(), now.timeIntervalSince(lastDetectedSpeechAt()) >= silenceWindow {
            requestFinish()
            return
        }

        if now.timeIntervalSince(startedAt) >= maxDuration {
            requestFinish()
        }
    }

    private func requestFinish() {
        let shouldFinish = withState { () -> Bool in
            if finishRequestedAt != nil || result != nil {
                return false
            }
            finishRequestedAt = Date()
            return true
        }
        guard shouldFinish else {
            return
        }

        audioEngine.stop()
        removeTapIfNeeded()
        request.endAudio()
    }

    private func handleRecognition(result: SFSpeechRecognitionResult?, error: Error?) {
        if let result {
            let transcript = result.bestTranscription.formattedString.trimmingCharacters(in: .whitespacesAndNewlines)
            if !transcript.isEmpty {
                noteSpeechDetected()
                withState {
                    bestTranscript = transcript
                }
            }
            if result.isFinal {
                let finalTranscript = transcript.isEmpty ? currentBestTranscript() : transcript
                if finalTranscript.isEmpty {
                    complete(.failure(SpeechCLIError.unavailable("No speech was detected.")))
                } else {
                    complete(.success(finalTranscript))
                }
                return
            }
        }

        if let error {
            let best = currentBestTranscript()
            if finishRequestedTime() != nil && !best.isEmpty {
                complete(.success(best))
                return
            }
            complete(.failure(error))
        }
    }

    private func noteSpeechDetected() {
        withState {
            heardSpeech = true
            lastSpeechAt = Date()
        }
    }

    private func currentBestTranscript() -> String {
        withState { bestTranscript }
    }

    private func hasHeardSpeech() -> Bool {
        withState { heardSpeech }
    }

    private func lastDetectedSpeechAt() -> Date {
        withState { lastSpeechAt }
    }

    private func finishRequestedTime() -> Date? {
        withState { finishRequestedAt }
    }

    private func currentResult() -> Result<String, Error>? {
        withState { result }
    }

    private func complete(_ outcome: Result<String, Error>) {
        let didSet = withState { () -> Bool in
            if result != nil {
                return false
            }
            result = outcome
            return true
        }
        guard didSet else {
            return
        }

        audioEngine.stop()
        removeTapIfNeeded()
        request.endAudio()
    }

    private func cleanup() {
        monitorTimer?.cancel()
        monitorTimer = nil
        audioEngine.stop()
        removeTapIfNeeded()
        recognitionTask?.cancel()
        recognitionTask = nil
    }

    private func removeTapIfNeeded() {
        guard tapInstalled else {
            return
        }
        audioEngine.inputNode.removeTap(onBus: 0)
        tapInstalled = false
    }

    private func peakLevel(in buffer: AVAudioPCMBuffer) -> Float {
        guard let channelData = buffer.floatChannelData else {
            return 0
        }
        let frameLength = Int(buffer.frameLength)
        let channelCount = Int(buffer.format.channelCount)
        var peak: Float = 0
        for channel in 0..<channelCount {
            let samples = channelData[channel]
            for index in 0..<frameLength {
                peak = max(peak, abs(samples[index]))
            }
        }
        return peak
    }

    private func waitForResult(timeout: TimeInterval) -> Result<String, Error>? {
        waitForValue(timeout: timeout) { self.currentResult() }
    }

    private func waitForValue<T>(timeout: TimeInterval, poll: @escaping () -> T?) -> T? {
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            if let value = poll() {
                return value
            }
            RunLoop.current.run(mode: .default, before: Date(timeIntervalSinceNow: 0.05))
        }
        return poll()
    }

    private func withState<T>(_ body: () -> T) -> T {
        stateLock.lock()
        defer {
            stateLock.unlock()
        }
        return body()
    }
}

enum CLI {
    static func localeIdentifier(from arguments: [String]) throws -> String {
        var locale = Locale.autoupdatingCurrent.identifier
        var index = 1
        while index < arguments.count {
            let argument = arguments[index]
            switch argument {
            case "--locale":
                index += 1
                guard index < arguments.count else {
                    throw SpeechCLIError.invalidArguments("Missing value for --locale.")
                }
                locale = arguments[index]
            case "--help", "-h":
                throw SpeechCLIError.invalidArguments("Usage: AlcoveNativeSpeech [--locale en-US]")
            default:
                throw SpeechCLIError.invalidArguments("Unknown argument: \(argument)")
            }
            index += 1
        }
        return locale.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? "en-US" : locale
    }

    static func emit(_ payload: SpeechOutput) {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        if let data = try? encoder.encode(payload) {
            FileHandle.standardOutput.write(data)
            FileHandle.standardOutput.write(Data([0x0A]))
        }
    }
}

let localeIdentifier: String
do {
    localeIdentifier = try CLI.localeIdentifier(from: CommandLine.arguments)
} catch {
    let detail = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
    CLI.emit(
        SpeechOutput(
            transcript: nil,
            detail: detail,
            locale: "en-US",
            provider: "macos-native"
        )
    )
    Foundation.exit(EXIT_FAILURE)
}

do {
    let transcript = try LiveSpeechSession(locale: Locale(identifier: localeIdentifier)).transcribe()
    CLI.emit(
        SpeechOutput(
            transcript: transcript,
            detail: nil,
            locale: localeIdentifier,
            provider: "macos-native"
        )
    )
    Foundation.exit(EXIT_SUCCESS)
} catch {
    let detail = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
    CLI.emit(
        SpeechOutput(
            transcript: nil,
            detail: detail,
            locale: localeIdentifier,
            provider: "macos-native"
        )
    )
    Foundation.exit(EXIT_FAILURE)
}
