import os
import requests
import report_generator

# Read key
with open('.env') as f:
    for line in f:
        if line.startswith('GEMINI_API_KEY'):
            key = line.split('=')[1].strip().strip('"').strip("'")
            break

# Temporarily patch logger to print raw text
orig_info = report_generator.logger.info
def my_info(msg):
    orig_info(msg)
    if 'Gemini' in msg:
        print('=== AI MSG ===', msg)

report_generator.logger.info = my_info

# Call generate_farmer_report_sections
res = report_generator.generate_farmer_report_sections(
    deep_stats={'crop_health': {'full_response_percent': 35.5, 'low_response_percent': 64.5},
                'leaf_greenness': {'moderate_to_high_percent': 42.0},
                'plant_cover': {'moderate_canopy_percent': 38.0}},
    series=[],
    start_date='2026-06-01',
    end_date='2026-09-01',
    crop_name='Wheat',
    field_name='Field 1',
    language='en'
)

print('\n=== MAP DESCRIPTIONS RESULT ===')
import json
print(json.dumps(res.get('map_descriptions'), indent=2))
print('\n=== SEASON SUMMARY ===')
print(res.get('season_summary'))
print('\n=== KEY FINDINGS ===')
print(res.get('key_findings'))
