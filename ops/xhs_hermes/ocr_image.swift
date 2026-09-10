import AppKit
import Foundation
import Vision

struct OCRLine: Codable {
    let text: String
    let confidence: Float
}

struct OCRResult: Codable {
    let path: String
    let lines: [OCRLine]
    let error: String?
}

func recognize(_ path: String) -> OCRResult {
    guard let image = NSImage(contentsOfFile: path),
          let data = image.tiffRepresentation,
          let bitmap = NSBitmapImageRep(data: data),
          let cgImage = bitmap.cgImage else {
        return OCRResult(path: path, lines: [], error: "cannot_open_image")
    }
    var lines: [OCRLine] = []
    var failure: String? = nil
    let request = VNRecognizeTextRequest { request, error in
        if let error = error {
            failure = error.localizedDescription
            return
        }
        let observations = request.results as? [VNRecognizedTextObservation] ?? []
        lines = observations.compactMap {
            guard let candidate = $0.topCandidates(1).first else { return nil }
            return OCRLine(text: candidate.string, confidence: candidate.confidence)
        }
    }
    request.recognitionLevel = .accurate
    request.usesLanguageCorrection = true
    request.recognitionLanguages = ["zh-Hans", "en-US"]
    do {
        try VNImageRequestHandler(cgImage: cgImage).perform([request])
    } catch {
        failure = error.localizedDescription
    }
    return OCRResult(path: path, lines: lines, error: failure)
}

let paths = Array(CommandLine.arguments.dropFirst())
let results = paths.map(recognize)
let encoder = JSONEncoder()
encoder.outputFormatting = [.prettyPrinted, .withoutEscapingSlashes]
let payload = try encoder.encode(results)
FileHandle.standardOutput.write(payload)
