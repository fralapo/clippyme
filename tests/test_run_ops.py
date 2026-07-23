from clippyme.pipeline.run_ops import sanitize_windows_basename, clip_output_basename


def test_sanitize_strips_forbidden_and_reserved():
    assert sanitize_windows_basename('Litigio: shock! <in> villa?') == 'Litigio shock in villa'
    assert sanitize_windows_basename('   ') is None
    assert sanitize_windows_basename('CON') is None          # reserved
    assert sanitize_windows_basename('***') is None          # all-forbidden
    assert sanitize_windows_basename('') is None
    assert sanitize_windows_basename(None) is None


def test_sanitize_truncates_on_word_boundary():
    long = 'word ' * 40
    out = sanitize_windows_basename(long, max_len=20)
    assert out is not None and len(out) <= 20 and not out.endswith(' ')


def test_clip_output_basename_unchanged_contract():
    # still suffixes _clip_N and falls back
    assert clip_output_basename('Hello', 0, 'base') == 'Hello_clip_1'
    assert clip_output_basename('   ', 2, 'base') == 'base_clip_3'
    assert clip_output_basename('CON', 0, 'base') == 'base_clip_1'
