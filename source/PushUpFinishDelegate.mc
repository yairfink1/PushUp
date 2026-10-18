import Toybox.Lang;
import Toybox.System;
import Toybox.WatchUi;

// ---------------------------------------------------------------------------
// PushUpFinishDelegate - handles save/discard decision at end of workout.
// ---------------------------------------------------------------------------
class PushUpFinishDelegate extends WatchUi.BehaviorDelegate {

    private var _multiDelegate  as PushUpMultiSetController;
    private var _restDelegate   as PushUpRestDelegate;

    function initialize(multiDelegate as PushUpMultiSetController, restDelegate as PushUpRestDelegate) {
        BehaviorDelegate.initialize();
        _multiDelegate = multiDelegate;
        _restDelegate  = restDelegate;
    }

    function onKey(keyEvent as WatchUi.KeyEvent) as Boolean {
        var key = keyEvent.getKey();
        if (key == WatchUi.KEY_ENTER || key == WatchUi.KEY_START) {
            return onSelect();
        } else if (key == WatchUi.KEY_ESC) {
            return onBack();
        }
        return BehaviorDelegate.onKey(keyEvent);
    }

    // START - Save workout and return to main screen.
    function onSelect() as Boolean {
        WatchUi.popView(WatchUi.SLIDE_DOWN); // Pop finish view
        WatchUi.popView(WatchUi.SLIDE_DOWN); // Pop rest view
        _multiDelegate.finishWorkout();
        return true;
    }

    // BACK - Cancel finish, resume rest timer.
    function onBack() as Boolean {
        WatchUi.popView(WatchUi.SLIDE_DOWN); // Pop finish view
        _restDelegate.resumeTimer();
        return true;
    }
}
