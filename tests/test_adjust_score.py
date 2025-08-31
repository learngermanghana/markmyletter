import runpy

# Load the app module without executing the Streamlit UI
app_globals = runpy.run_path('app.py')

adjust_score_for_level = app_globals['adjust_score_for_level']


def test_adjust_score_for_level_scaling():
    # Lower levels should scale leniently
    assert adjust_score_for_level(20, 'A1') == 50
    # Advanced levels expect higher raw scores
    assert adjust_score_for_level(90, 'C1') == 75
    # Unknown levels return the raw score unchanged
    assert adjust_score_for_level(55, 'Unknown') == 55
