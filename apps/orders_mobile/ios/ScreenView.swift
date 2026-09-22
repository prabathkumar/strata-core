import UIKit

/// The whole of the iOS side.
///
/// It knows nothing about orders, customers or amounts. It asks Strata for a
/// list of things to draw, paints them, and reports where the finger went.
/// Adding a column, a screen or a business rule changes nothing in this file —
/// which is the point of drawing the screen rather than borrowing the
/// platform's widgets.
///
/// This is deliberately a line-for-line mirror of android/MainActivity.kt. If
/// the two ever disagree about what "kind|x|y|w|h|colour|scale|text|action"
/// means, the same app looks different on the two phones, and that is the kind
/// of bug nobody finds until a customer does.
final class ScreenView: UIView {

    // The display list is in device-independent pixels against a 411-wide
    // screen; a real handset is wider or narrower, so everything is scaled by
    // one factor. One number, because a layout that needs more than one is a
    // layout that will not survive the next phone.
    private var scale: CGFloat { bounds.width / 411.0 }

    override init(frame: CGRect) {
        super.init(frame: frame)
        backgroundColor = UIColor(white: 240.0 / 255.0, alpha: 1.0)  // #F0F0F0
        isMultipleTouchEnabled = false
        _ = host_start()
    }

    required init?(coder: NSCoder) { fatalError("not used") }

    override func draw(_ rect: CGRect) {
        guard let ctx = UIGraphicsGetCurrentContext() else { return }
        let s = scale
        let n = host_draw()

        for i in 0..<n {
            guard let raw = host_item(i) else { continue }
            let fields = String(cString: raw).components(separatedBy: "|")
            if fields.count < 9 { continue }

            guard let kind = Int(fields[0]),
                  let fx = Double(fields[1]), let fy = Double(fields[2]),
                  let fw = Double(fields[3]), let fh = Double(fields[4]),
                  let rgb = Int(fields[5]), let textScale = Int(fields[6])
            else { continue }

            let x = CGFloat(fx) * s, y = CGFloat(fy) * s
            let w = CGFloat(fw) * s, h = CGFloat(fh) * s
            let colour = UIColor(
                red:   CGFloat((rgb >> 16) & 0xFF) / 255.0,
                green: CGFloat((rgb >>  8) & 0xFF) / 255.0,
                blue:  CGFloat( rgb        & 0xFF) / 255.0,
                alpha: 1.0)
            let text = fields[7]

            switch kind {
            case 0:
                ctx.setFillColor(colour.cgColor)
                ctx.fill(CGRect(x: x, y: y, width: w, height: h))
            case 1:
                // Strata's font is 8 pixels tall at scale 1. Matching that
                // here keeps the phone and the tested image the same shape,
                // so a screenshot test means something.
                let size = 8.0 * CGFloat(textScale) * s
                let font = UIFont.monospacedSystemFont(ofSize: size, weight: .regular)
                // Android draws from the baseline; UIKit draws from the top of
                // the line box. Subtracting the ascender puts the same glyph in
                // the same place on both phones.
                let baseline = y + 7.0 * CGFloat(textScale) * s
                let attrs: [NSAttributedString.Key: Any] = [
                    .font: font, .foregroundColor: colour
                ]
                (text as NSString).draw(
                    at: CGPoint(x: x, y: baseline - font.ascender),
                    withAttributes: attrs)
            default:
                break  // kind 2 is a touch region: nothing to paint.
            }
        }
        _ = ctx
    }

    override func touchesEnded(_ touches: Set<UITouch>, with event: UIEvent?) {
        guard let t = touches.first else { return }
        let s = scale
        let p = t.location(in: self)
        guard let raw = host_hit(Int64(p.x / s), Int64(p.y / s)) else { return }
        let action = String(cString: raw)
        if !action.isEmpty {
            _ = action.withCString { host_act(UnsafeMutablePointer(mutating: $0)) }
            setNeedsDisplay()
        }
    }
}
