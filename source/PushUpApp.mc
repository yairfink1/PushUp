import Toybox.Application;
import Toybox.Graphics;
import Toybox.Lang;
import Toybox.WatchUi;

// ---------------------------------------------------------------------------
// PushUpApp - application entry point with Widget Glance support.
//
// Annotated with (:glance) so the runtime can initialize the AppBase in
// glance mode without loading full-screen recording delegates.
// ---------------------------------------------------------------------------
(:glance)
class PushUpApp extends Application.AppBase {

    function initialize() {
        AppBase.initialize();
    }

    // Return the initial full-screen view/delegate pair.
    function getInitialView() as [WatchUi.Views] or [WatchUi.Views, WatchUi.InputDelegates] {
        var view = new PushUpContainerView();
        var delegate = new PushUpContainerDelegate(view);
        return [view, delegate];
    }

    // Return the widget glance view shown in the Garmin glance carousel.
    function getGlanceView() {
        return [ new PushUpGlanceView() ];
    }
}

// ---------------------------------------------------------------------------
// Application factory - required by the CIQ runtime.
// ---------------------------------------------------------------------------
(:glance)
function getApp() as PushUpApp {
    return Application.getApp() as PushUpApp;
}
