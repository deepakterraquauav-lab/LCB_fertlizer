import sys

with open('report_generator.py', 'r', encoding='utf-8') as f:
    content = f.read()

replacements = {
    'â†’': '→',
    'â€”': '—',
    'â€‘': '‑',
    'â€¢': '•',
    'Â°C': '°C',
    'kmÂ²': 'km²',
    'mÂ²': 'm²',
    'â‰ˆ': '≈',
    'âœ…': '✅',
    'ðŸ“ ': '📐',
    'ðŸ” ': '🔍',
    'ðŸ“Š': '📊',
    'ðŸ—ºï¸ ': '🗺️',
    'ðŸ“¦': '📦',
    'Î”S': 'ΔS',
    'â€“': '–',
}

for bad, good in replacements.items():
    content = content.replace(bad, good)

with open('report_generator.py', 'w', encoding='utf-8') as f:
    f.write(content)
print('Replacements done.')
