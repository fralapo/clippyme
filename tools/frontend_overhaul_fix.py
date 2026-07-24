from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(rel, old, new):
    path = ROOT / rel
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"expected block not found in {rel}: {old[:120]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    "dashboard/src/redesign/LazyVideo.jsx",
    "  return (\n    <video",
    "  return (\n    // Captions are burned into ClippyMe output pixels; there is no separate text track.\n    // eslint-disable-next-line jsx-a11y/media-has-caption\n    <video",
)

replace_once(
    "dashboard/src/redesign/results.jsx",
    "  const processing = !!state?.processing;\n\n  const doDownload",
    "  const processing = !!state?.processing;\n  const selectionProps = selectMode ? {\n    role: 'checkbox',\n    tabIndex: 0,\n    'aria-checked': selected,\n    onClick: () => onUpdate(index, { selected: !selected }),\n    onKeyDown: (event) => {\n      if (event.key === 'Enter' || event.key === ' ') {\n        event.preventDefault();\n        onUpdate(index, { selected: !selected });\n      }\n    },\n  } : {};\n\n  const doDownload",
)
replace_once(
    "dashboard/src/redesign/results.jsx",
    "    <article className={`clip${score >= 90 ? ' top' : ''}${selectMode && selected ? ' sel' : ''}`}\n      role={selectMode ? 'checkbox' : undefined} tabIndex={selectMode ? 0 : undefined} aria-checked={selectMode ? selected : undefined}\n      onClick={() => selectMode && onUpdate(index, { selected: !selected })}\n      onKeyDown={(event) => { if (selectMode && (event.key === 'Enter' || event.key === ' ')) { event.preventDefault(); onUpdate(index, { selected: !selected }); } }}>",
    "    <article {...selectionProps} className={`clip${score >= 90 ? ' top' : ''}${selectMode && selected ? ' sel' : ''}`}>",
)

replace_once(
    "dashboard/src/redesign/primitives.jsx",
    "  return (\n    <div className={`seg${full ? ' full' : ''}${blue ? ' blue' : ''}`} role=\"radiogroup\" aria-label={label}>\n      {options.map((option, index) => (\n        <button key={option.id} ref={(node) => { refs.current[index] = node; }} type=\"button\" role=\"radio\"\n          aria-checked={value === option.id} tabIndex={value === option.id || (!options.some((item) => item.id === value) && index === 0) ? 0 : -1}",
    "  return (\n    <div className={`seg${full ? ' full' : ''}${blue ? ' blue' : ''}`} role=\"group\" aria-label={label}>\n      {options.map((option, index) => (\n        <button key={option.id} ref={(node) => { refs.current[index] = node; }} type=\"button\"\n          aria-pressed={value === option.id}",
)

replace_once(
    "dashboard/src/redesign/LazyVideo.test.jsx",
    "  globalThis.IntersectionObserver = vi.fn((cb) => { callback = cb; return { observe: vi.fn(), disconnect: vi.fn() }; });",
    "  globalThis.IntersectionObserver = vi.fn(function IntersectionObserverMock(cb) { callback = cb; return { observe: vi.fn(), disconnect: vi.fn() }; });",
)

print("frontend accessibility and compatibility fixes applied")
