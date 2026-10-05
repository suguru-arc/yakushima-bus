import Foundation
import Vision
import AppKit

// usage: ocr2 <image.png> <out.json> [x0 y0 x1 y1]   (crop in pixels; coordinates in output are in full-image pixels)
let args = CommandLine.arguments
guard args.count >= 3 else { print("usage"); exit(1) }
guard let nsimg = NSImage(contentsOfFile: args[1]),
      var cg = nsimg.cgImage(forProposedRect: nil, context: nil, hints: nil) else { print("cannot load"); exit(1) }
var offX = 0.0, offY = 0.0
if args.count >= 7 {
    let x0 = Int(args[3])!, y0 = Int(args[4])!, x1 = Int(args[5])!, y1 = Int(args[6])!
    if let c = cg.cropping(to: CGRect(x: x0, y: y0, width: x1 - x0, height: y1 - y0)) { cg = c; offX = Double(x0); offY = Double(y0) }
}
let W = Double(cg.width), H = Double(cg.height)
let req = VNRecognizeTextRequest()
req.recognitionLevel = .accurate
req.usesLanguageCorrection = false
req.recognitionLanguages = ["ja-JP", "en-US"]
req.minimumTextHeight = 0.002
try VNImageRequestHandler(cgImage: cg, options: [:]).perform([req])

let timeRe = try! NSRegularExpression(pattern: "\\d{1,2}:\\d{2}")
var out: [[String: Any]] = []
func emit(_ cand: VNRecognizedText, _ r: Range<String.Index>, _ kind: String) {
    let tok = String(cand.string[r])
    if let box = try? cand.boundingBox(for: r) {
        let bb = box.boundingBox
        out.append(["text": tok, "kind": kind,
                    "x0": bb.minX * W + offX, "x1": bb.maxX * W + offX,
                    "top": (1 - bb.maxY) * H + offY, "bottom": (1 - bb.minY) * H + offY,
                    "conf": cand.confidence])
    }
}
for obs in req.results ?? [] {
    guard let cand = obs.topCandidates(1).first else { continue }
    let s = cand.string
    let ns = s as NSString
    var covered = [Bool](repeating: false, count: ns.length)
    for m in timeRe.matches(in: s, range: NSRange(location: 0, length: ns.length)) {
        if let r = Range(m.range, in: s) { emit(cand, r, "time") }
        for i in m.range.location..<(m.range.location + m.range.length) { covered[i] = true }
    }
    // remaining non-space runs
    var i = 0
    while i < ns.length {
        if covered[i] || ns.character(at: i) == 32 { i += 1; continue }
        var j = i
        while j < ns.length && !covered[j] && ns.character(at: j) != 32 { j += 1 }
        if let r = Range(NSRange(location: i, length: j - i), in: s) { emit(cand, r, "other") }
        i = j
    }
}
let data = try JSONSerialization.data(withJSONObject: out, options: [])
try data.write(to: URL(fileURLWithPath: args[2]))
print("tokens:", out.count, "times:", out.filter { ($0["kind"] as? String) == "time" }.count)
