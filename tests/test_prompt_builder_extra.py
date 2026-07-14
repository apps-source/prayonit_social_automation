import prompt_builder


def test_locked_benefit_substitution():
    # variant that should trigger locked substitution
    variant = "Receive personalized, guided prayer based on how you feel tonight."
    replaced = prompt_builder.enforce_locked_benefit_phrase(variant, prompt_builder.LOCKED_APP_BENEFIT)
    assert replaced == prompt_builder.LOCKED_APP_BENEFIT


def test_no_locked_benefit_substitution_when_ok():
    ok = "Get a guided, personalized prayer based on your mood right now."
    replaced = prompt_builder.enforce_locked_benefit_phrase(ok, prompt_builder.LOCKED_APP_BENEFIT)
    assert replaced == ok


def test_strip_duplicate_download_cta_sentences():
    text = "Feeling overwhelmed? Download Prayonit today. Start your 14-day free trial."
    stripped = prompt_builder._strip_duplicate_download_cta_sentences(text)
    assert "Download Prayonit" not in stripped
    assert "Start your 14-day free trial" in stripped
