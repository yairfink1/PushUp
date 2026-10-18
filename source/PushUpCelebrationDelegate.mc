import Toybox.Lang;
import Toybox.WatchUi;

// ---------------------------------------------------------------------------
// PushUpCelebrationDelegate - dismisses the celebration view on any key press.
// ---------------------------------------------------------------------------
class PushUpCelebrationDelegate extends WatchUi.BehaviorDelegate {

    private var _view as PushUpCelebrationView;

    function initialize(view as PushUpCelebrationView) {
        BehaviorDelegate.initialize();
        _view = view;
    }

    function onKey(keyEvent as WatchUi.KeyEvent) as Boolean {
        WatchUi.popView(WatchUi.SLIDE_DOWN);
        return true;
    }

    function onTap(clickEvent as WatchUi.ClickEvent) as Boolean {
        WatchUi.popView(WatchUi.SLIDE_DOWN);
        return true;
    }

    function onSelect() as Boolean {
        WatchUi.popView(WatchUi.SLIDE_DOWN);
        return true;
    }

    function onBack() as Boolean {
        WatchUi.popView(WatchUi.SLIDE_DOWN);
        return true;
    }
}
