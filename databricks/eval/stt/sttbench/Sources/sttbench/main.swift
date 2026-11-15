// Runs one speech-to-text model over a list of recordings the way the app would hear them: the
// audio arrives in 100 ms buffers, each handed to the recogniser at once, and what matters is how
// long `finish()` takes after the last buffer (the wait after the button is let go) and what the
// final text is.
//
//   sttbench <variant> <list.txt> <out.tsv> [--buffer-ms 100]
//
// <variant> is a streaming variant's name ("parakeet-eou-320ms", "nemotron-560ms",
// "parakeet-unified-320ms", ...) or "batch:v2" / "batch:v3" / "batch:ultra" for a model that only
// runs once the audio is complete.
import AVFoundation
import CoreML
import FluidAudio
import Foundation

func now() -> Double { Double(DispatchTime.now().uptimeNanoseconds) / 1e6 }

func readBuffer(_ path: String) throws -> AVAudioPCMBuffer {
    let file = try AVAudioFile(forReading: URL(fileURLWithPath: path))
    guard let buffer = AVAudioPCMBuffer(pcmFormat: file.processingFormat, frameCapacity: AVAudioFrameCount(file.length)) else {
        throw NSError(domain: "sttbench", code: 1)
    }
    try file.read(into: buffer)
    return buffer
}

/// `buffer` cut into pieces of `ms` milliseconds, as a microphone tap would deliver it.
func slices(of buffer: AVAudioPCMBuffer, ms: Int) -> [AVAudioPCMBuffer] {
    let format = buffer.format
    let step = AVAudioFrameCount(format.sampleRate * Double(ms) / 1000)
    var out: [AVAudioPCMBuffer] = []
    var start: AVAudioFrameCount = 0
    while start < buffer.frameLength {
        let count = min(step, buffer.frameLength - start)
        guard let piece = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: count) else { break }
        piece.frameLength = count
        for channel in 0..<Int(format.channelCount) {
            memcpy(piece.floatChannelData![channel], buffer.floatChannelData![channel] + Int(start), Int(count) * MemoryLayout<Float>.size)
        }
        out.append(piece)
        start += count
    }
    return out
}

let args = CommandLine.arguments.dropFirst()
guard args.count >= 3 else {
    print("usage: sttbench <variant> <list.txt> <out.tsv> [--buffer-ms 100]")
    exit(2)
}
let variantName = args[args.startIndex], listPath = args[args.startIndex + 1], outPath = args[args.startIndex + 2]
var bufferMs = 100
if let i = args.firstIndex(of: "--buffer-ms"), i + 1 < args.endIndex { bufferMs = Int(args[i + 1]) ?? 100 }
// Silence put before and after each recording, to see whether a clip that starts or ends on a
// word is heard better with some room around it.
var leadMs = 0, tailMs = 0
if let i = args.firstIndex(of: "--lead-ms"), i + 1 < args.endIndex { leadMs = Int(args[i + 1]) ?? 0 }
if let i = args.firstIndex(of: "--tail-ms"), i + 1 < args.endIndex { tailMs = Int(args[i + 1]) ?? 0 }
var gain: Float = 1
if let i = args.firstIndex(of: "--gain"), i + 1 < args.endIndex { gain = Float(args[i + 1]) ?? 1 }

func padded(_ buffer: AVAudioPCMBuffer) -> AVAudioPCMBuffer {
    guard leadMs > 0 || tailMs > 0 || gain != 1 else { return buffer }
    let rate = buffer.format.sampleRate
    let lead = AVAudioFrameCount(rate * Double(leadMs) / 1000), tail = AVAudioFrameCount(rate * Double(tailMs) / 1000)
    let out = AVAudioPCMBuffer(pcmFormat: buffer.format, frameCapacity: buffer.frameLength + lead + tail)!
    out.frameLength = buffer.frameLength + lead + tail
    for channel in 0..<Int(buffer.format.channelCount) {
        let to = out.floatChannelData![channel], from = buffer.floatChannelData![channel]
        for i in 0..<Int(out.frameLength) { to[i] = 0 }
        for i in 0..<Int(buffer.frameLength) { to[Int(lead) + i] = from[i] * gain }
    }
    return out
}
let paths = try String(contentsOfFile: listPath, encoding: .utf8).split(separator: "\n").map(String.init).filter { !$0.isEmpty }

var rows = ["file\tseconds\ttext\tfinish_ms\tworst_step_ms\tcompute_ms"]
let loadBegan = now()

if variantName.hasPrefix("batch:") {
    let version: AsrModelVersion
    switch variantName.dropFirst(6) {
    case "v2": version = .v2
    case "v3": version = .v3
    case "ultra": version = .ultra
    case "phonon2": version = .phonon2
    default: print("unknown batch model"); exit(2)
    }
    let models = try await AsrModels.downloadAndLoad(version: version)
    let manager = AsrManager()
    try await manager.loadModels(models)
    print(String(format: "loaded %@ in %.1f s", variantName, (now() - loadBegan) / 1000))
    let converter = AudioConverter()
    for (i, path) in paths.enumerated() {
        do {
            let buffer = try readBuffer(path)
            let seconds = Double(buffer.frameLength) / buffer.format.sampleRate
            let samples = try converter.resampleBuffer(buffer)
            let began = now()
            var decoderState = TdtDecoderState.make(decoderLayers: await manager.decoderLayerCount)
            let result = try await manager.transcribe(samples, decoderState: &decoderState)
            let ms = now() - began
            // The first file pays for warming up; it is run again at the end and that time kept.
            rows.append("\(path)\t\(String(format: "%.2f", seconds))\t\(result.text)\t\(String(format: "%.0f", ms))\t\(String(format: "%.0f", ms))\t\(String(format: "%.0f", ms))")
            if i % 40 == 0 { print("\(i + 1)/\(paths.count)") }
        } catch {
            rows.append("\(path)\t0\tERROR \(error)\t0\t0\t0")
        }
    }
} else {
    guard let variant = StreamingModelVariant(rawValue: variantName) else {
        print("unknown variant; streaming ones are: " + StreamingModelVariant.allCases.map(\.rawValue).joined(separator: ", "))
        exit(2)
    }
    let manager = variant.createManager()
    try await manager.loadModels()
    print(String(format: "loaded %@ in %.1f s", variant.displayName, (now() - loadBegan) / 1000))
    // One pass over the first recording to warm the models up, not counted.
    if let first = paths.first, let buffer = try? readBuffer(first) {
        for piece in slices(of: buffer, ms: bufferMs) {
            try await manager.appendAudio(piece)
            try await manager.processBufferedAudio()
        }
        _ = try await manager.finish()
        try await manager.reset()
    }
    for (i, path) in paths.enumerated() {
        do {
            // The silence after the audio is given at the moment of "release", all at once, and
            // counted in the time to finish: that is what the app would have to wait for.
            let tail = tailMs
            tailMs = 0
            let buffer = padded(try readBuffer(path))
            tailMs = tail
            let seconds = Double(buffer.frameLength) / buffer.format.sampleRate
            var worst = 0.0, total = 0.0
            for piece in slices(of: buffer, ms: bufferMs) {
                let began = now()
                try await manager.appendAudio(piece)
                try await manager.processBufferedAudio()
                let ms = now() - began
                worst = max(worst, ms)
                total += ms
            }
            let began = now()
            if tail > 0, let silence = AVAudioPCMBuffer(pcmFormat: buffer.format, frameCapacity: AVAudioFrameCount(buffer.format.sampleRate * Double(tail) / 1000)) {
                silence.frameLength = silence.frameCapacity
                for channel in 0..<Int(buffer.format.channelCount) {
                    for i in 0..<Int(silence.frameLength) { silence.floatChannelData![channel][i] = 0 }
                }
                try await manager.appendAudio(silence)
                try await manager.processBufferedAudio()
            }
            let text = try await manager.finish()
            let finishMs = now() - began
            total += finishMs
            try await manager.reset()
            rows.append("\(path)\t\(String(format: "%.2f", seconds))\t\(text.replacingOccurrences(of: "\t", with: " ").replacingOccurrences(of: "\n", with: " "))\t\(String(format: "%.0f", finishMs))\t\(String(format: "%.0f", worst))\t\(String(format: "%.0f", total))")
            if i % 40 == 0 { print("\(i + 1)/\(paths.count)") }
        } catch {
            rows.append("\(path)\t0\tERROR \(error)\t0\t0\t0")
            try? await manager.reset()
        }
    }
}
try (rows.joined(separator: "\n") + "\n").write(toFile: outPath, atomically: true, encoding: .utf8)
print("wrote \(outPath)")
