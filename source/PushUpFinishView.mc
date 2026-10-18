import Toybox.Graphics;
import Toybox.Lang;
import Toybox.WatchUi;

// ---------------------------------------------------------------------------
// PushUpFinishView - workout finish confirmation screen.
//
// Shown when the user presses BACK during rest, asking to save or discard
// the full multi-set workout session.
// ---------------------------------------------------------------------------
class PushUpFinishView extends WatchUi.View {

    private var _totalReps as Number;

    function initialize(totalReps as Number) {
        View.initialize();
        _totalReps = totalReps;
    }

    function onLayout(dc as Graphics.Dc) as Void {
        // Drawn dynamically in onUpdate.
    }

    function onUpdate(dc as Graphics.Dc) as Void {
        var w  = dc.getWidth();
        var h  = dc.getHeight();
        var cx = w / 2;
        var numFont = (h >= 360) ? Graphics.FONT_NUMBER_THAI_HOT : Graphics.FONT_NUMBER_HOT;

        dc.setColor(Graphics.COLOR_BLACK, Graphics.COLOR_BLACK);
        dc.clear();

        // 1. Title
        dc.setColor(Graphics.COLOR_WHITE, Graphics.COLOR_TRANSPARENT);
        dc.drawText(cx, (h * 0.10).toNumber(), Graphics.FONT_SMALL, "WORKOUT DONE?", Graphics.TEXT_JUSTIFY_CENTER);

        // 2. Total reps summary
        dc.setColor(Graphics.COLOR_GREEN, Graphics.COLOR_TRANSPARENT);
        dc.drawText(cx, (h * 0.24).toNumber(), numFont, _totalReps.toString(), Graphics.TEXT_JUSTIFY_CENTER);

        dc.setColor(Graphics.COLOR_LT_GRAY, Graphics.COLOR_TRANSPARENT);
        dc.drawText(cx, (h * 0.58).toNumber(), Graphics.FONT_XTINY, "Total Reps", Graphics.TEXT_JUSTIFY_CENTER);

        // 3. Action hints
        dc.setColor(Graphics.COLOR_GREEN, Graphics.COLOR_TRANSPARENT);
        dc.drawText(cx, (h * 0.72).toNumber(), Graphics.FONT_TINY, "START = Save Workout", Graphics.TEXT_JUSTIFY_CENTER);

        dc.setColor(Graphics.COLOR_RED, Graphics.COLOR_TRANSPARENT);
        dc.drawText(cx, (h * 0.83).toNumber(), Graphics.FONT_TINY, "BACK = Discard", Graphics.TEXT_JUSTIFY_CENTER);
    }
}
