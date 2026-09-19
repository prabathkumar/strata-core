package org.stratalang.orders

import android.app.Activity
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Typeface
import android.os.Bundle
import android.view.MotionEvent
import android.view.View

/**
 * The whole of the Android side.
 *
 * It knows nothing about orders, customers or amounts. It asks Strata for a
 * list of things to draw, paints them, and reports where the finger went.
 * Adding a column, a screen or a business rule changes nothing in this file —
 * which is the point of drawing the screen rather than borrowing the
 * platform's widgets.
 */
class MainActivity : Activity() {

    companion object {
        init { System.loadLibrary("strata") }
    }

    /** Rebuild the display list. Returns how many items it holds. */
    external fun drawScreen(): Int

    /** One item, as "kind|x|y|w|h|colour|scale|text|action". */
    external fun itemAt(index: Int): String

    /** What a tap at this point means, or "" for nothing. */
    external fun hit(x: Int, y: Int): String

    /** Tell Strata a tap happened; it decides what changes. */
    external fun act(action: String): Int

    override fun onCreate(state: Bundle?) {
        super.onCreate(state)
        setContentView(ScreenView(this))
    }

    inner class ScreenView(ctx: Activity) : View(ctx) {
        private val paint = Paint(Paint.ANTI_ALIAS_FLAG)

        // The display list is in device-independent pixels against a 411-wide
        // screen; a real handset is wider or narrower, so everything is scaled
        // by one factor. One number, because a layout that needs more than one
        // is a layout that will not survive the next phone.
        private fun scale(): Float = width / 411f

        override fun onDraw(canvas: Canvas) {
            val s = scale()
            canvas.drawColor(Color.parseColor("#F0F0F0"))
            val n = drawScreen()
            for (i in 0 until n) {
                val f = itemAt(i).split("|")
                if (f.size < 9) continue
                val kind = f[0].toInt()
                val x = f[1].toFloat() * s
                val y = f[2].toFloat() * s
                val w = f[3].toFloat() * s
                val h = f[4].toFloat() * s
                val colour = 0xFF000000.toInt() or f[5].toInt()
                val textScale = f[6].toInt()
                val text = f[7]

                paint.color = colour
                when (kind) {
                    0 -> canvas.drawRect(x, y, x + w, y + h, paint)
                    1 -> {
                        // Strata's font is 8 pixels tall at scale 1. Matching
                        // that here keeps the phone and the tested image the
                        // same shape, so a screenshot test means something.
                        paint.typeface = Typeface.MONOSPACE
                        paint.textSize = 8f * textScale * s
                        canvas.drawText(text, x, y + 7f * textScale * s, paint)
                    }
                    // kind 2 is a touch region: nothing to paint.
                }
            }
        }

        override fun onTouchEvent(e: MotionEvent): Boolean {
            if (e.action != MotionEvent.ACTION_UP) return true
            val s = scale()
            val action = hit((e.x / s).toInt(), (e.y / s).toInt())
            if (action.isNotEmpty()) {
                act(action)
                invalidate()
            }
            return true
        }
    }
}
