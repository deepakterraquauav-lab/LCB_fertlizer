import os
import requests

with open('.env') as f:
    for line in f:
        if line.startswith('GEMINI_API_KEY'):
            key = line.split('=')[1].strip().strip('"').strip("'")
            break

import report_generator
# Let's inspect the exact prompt built
# We can import and check
deep_stats = {'crop_health': {'full_response_percent': 35.5, 'low_response_percent': 64.5},
              'leaf_greenness': {'moderate_to_high_percent': 42.0},
              'plant_cover': {'moderate_canopy_percent': 38.0}}
# Let's see what ai_prompt looks like by extracting it or running test
# Let's call Gemini directly with a simplified prompt asking for the format
test_prompt = """You are an agricultural advisor writing a 2-page seasonal crop performance report for a farmer.

FIELD DATA:
- Crop: Wheat
- Field: Field 1
- Period: 2026-06-01 to 2026-09-01
- Overall Crop Condition: 35.5% strong response, 64.5% weak/lagging response
- Leaf Greenness (Chlorophyll): 42.0% moderate-to-high active response
- Plant Cover & Crop Density: 38.0% moderate canopy coverage
- Available Soil Moisture: 22.4% avg across root zone
- Overall seasonal status: Needs Attention

OUTPUT FORMAT — follow EXACTLY:

SEASON_SUMMARY:
[Write 50–70 words. Plain language. Explain how the crop performed during this season.]

WHAT_HAPPENED:
Early season | [1 short sentence] | [1 simple interpretation]
Middle of season | [1 short sentence] | [1 simple interpretation]
End of season | [1 short sentence] | [1 simple interpretation]

KEY_FINDINGS:
[Overall crop condition finding — 1 sentence]
[Leaf greenness finding — 1 sentence]
[Plant cover and crop density finding — 1 sentence]
[Available soil moisture finding — 1 sentence]
[Uneven field performance observation — 1 sentence]

ACTION_PLAN:
High | [urgent practical action] | Before next sowing
High | [another urgent action] | After next sowing
Medium | [moderate priority action] | Before next sowing
Medium | [another medium action] | Every 15 days
Low | [low priority action] | End of next season

MAP_CROP_HEALTH_SHOWS: Dark green areas show 'Highest' to 'High' crop condition on the legend bar. Lighter pale green areas indicate 'Low' to 'Lowest' performance (64.5% of field) where vigor is lagging.
MAP_CROP_HEALTH_DO: Prioritize ground visits to areas marked as 'Low' or 'Lowest' on the legend to check root health and soil conditions.
MAP_LEAF_GREENNESS_SHOWS: Dark green zones represent 'Highest' leaf greenness and active photosynthesis on the legend bar. Pale green areas indicate 'Low' or 'Lowest' greenness.
MAP_LEAF_GREENNESS_DO: Inspect 'Low' and 'Lowest' greenness areas for signs of nutrient deficiency, especially nitrogen, or foliage stress.
MAP_PLANT_COVER_SHOWS: Dark green areas indicate 'Highest' canopy cover and dense crop growth on the legend. Lighter green areas show 'Low' to 'Lowest' plant density.
MAP_PLANT_COVER_DO: Check 'Low' density zones for poor emergence, uneven seed germination, or localized pest damage.
MAP_SOIL_MOISTURE_SHOWS: Dark purple areas indicate 'Highest' available soil moisture on the legend bar. Light lavender areas represent 'Low' to 'Lowest' moisture retention.
MAP_SOIL_MOISTURE_DO: Review irrigation reach, drainage uniformity, and soil compaction in zones showing 'Low' moisture.
"""

url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={key}"
r = requests.post(url, json={
    "contents": [{"parts": [{"text": test_prompt}]}],
    "generationConfig": {
        "maxOutputTokens": 4096,
        "temperature": 0.3,
        "thinkingConfig": {
            "thinkingBudget": 0
        }
    }
})
print("STATUS:", r.status_code)
res = r.json()
candidate = res['candidates'][0]
print("FINISH REASON:", candidate.get('finishReason'))
print("CANDIDATE TEXT:")
print(candidate['content']['parts'][0]['text'])
